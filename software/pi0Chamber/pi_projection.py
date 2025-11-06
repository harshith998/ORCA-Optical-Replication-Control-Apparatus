#!/usr/bin/env python3
import serial
import time
import numpy as np
from collections import deque
from scipy import linalg
import RPi.GPIO as GPIO
import board
import busio
import adafruit_character_lcd.character_lcd_i2c as character_lcd

# LED Configuration
LED_PIN = 18  # GPIO 18 (PWM capable)
PWM_FREQ = 5000  # 5kHz like Arduino

# LCD Configuration (I2C)
LCD_COLS = 16
LCD_ROWS = 2
LCD_I2C_ADDRESS = 0x27  # Common I2C address, might be 0x3F

# Switch Configuration
SWITCH_LED_ONOFF = 17   # GPIO pin for LED on/off switch
SWITCH_AUTO_MANUAL = 27  # GPIO pin for auto/manual switch

# Potentiometer Configuration
POT_PIN = 5  # ADC channel for potentiometer (MCP3008 CH0)

# configuration
SERIAL_PORT = '/dev/ttyUSB0'  # Or /dev/ttyAMA0 for GPIO UART
BAUD_RATE = 115200  # Must match Arduino's Serial.begin(115200)
SAMPLE_MS = 500
WINDOW_SIZE = 600  # 5 minutes @ 500ms
BOUNDS_ALPHA = 0.05

# Filter selection: 'sma', 'ema', or 'sg'
ACTIVE_FILTER = 'ema'

#CIRCULAR BUFFER ====================
class CircularBuffer:
    def __init__(self, size):
        self.size = size
        self.buffer = deque(maxlen=size)
    
    def add(self, value):
        self.buffer.append(value)
    
    def get_array(self):
        return np.array(self.buffer)
    
    def is_full(self):
        return len(self.buffer) == self.size

#FILTERS ====================
class SMAFilter:
    def __init__(self, window_size=11):
        self.window = deque(maxlen=window_size)
    
    def process(self, value):
        self.window.append(value)
        return np.mean(self.window)

class EMAFilter:
    def __init__(self, alpha=0.1):
        self.alpha = alpha
        self.state = None
    
    def process(self, value):
        if self.state is None:
            self.state = value
        else:
            self.state = self.alpha * value + (1.0 - self.alpha) * self.state
        return self.state

class SGFilter:
    def __init__(self, window_size=11, poly_order=3):
        if window_size % 2 == 0:
            window_size += 1
        self.window_size = window_size
        self.poly_order = poly_order
        self.half = (window_size - 1) // 2
        self.buffer = deque(maxlen=window_size)
        self.coeffs = self._compute_coefficients()
    
    def _compute_coefficients(self):
        # Build Vandermonde-like matrix A
        rows = self.window_size
        cols = self.poly_order + 1
        A = np.zeros((rows, cols))
        
        for r in range(rows):
            j = r - self.half
            for p in range(cols):
                A[r, p] = j ** p
        
        # Compute (A^T A)^-1 A^T
        ATA = A.T @ A
        try:
            inv_ATA = linalg.inv(ATA)
        except linalg.LinAlgError:
            # Fallback to uniform weights
            return np.ones(rows) / rows
        
        B = inv_ATA @ A.T
        # Smoothing coefficients are the first row
        return B[0, :]
    
    def process(self, value):
        self.buffer.append(value)
        
        if len(self.buffer) < self.window_size:
            # Not enough data yet
            return np.mean(self.buffer)
        
        # Convolve with coefficients
        data = np.array(self.buffer)
        return np.dot(self.coeffs, data)

# ==================== ROBUST BOUNDS ====================
def compute_robust_bounds(data_array):
    if len(data_array) == 0:
        return 0.0, 1000.0
    
    median = np.median(data_array)
    mad = np.median(np.abs(data_array - median))
    sigma = 1.4826 * mad
    threshold = 3.0 * sigma
    
    if sigma < 1e-9:
        # All values essentially the same
        return data_array.min(), data_array.max()
    
    # Filter inliers
    inliers = data_array[np.abs(data_array - median) <= threshold]
    
    if len(inliers) == 0:
        return median, median
    
    return inliers.min(), inliers.max()

#LED MAPPING ====================
def map_to_led(value, min_val, max_val):
    """Map lux value to LED brightness (0-255)"""
    if max_val <= min_val:
        return 0
    
    # Normalize to 0-1
    normalized = (value - min_val) / (max_val - min_val)
    normalized = np.clip(normalized, 0.0, 1.0)
    
    # Scale to 0-255
    brightness = int(normalized * 255)
    return brightness

# ==================== POTENTIOMETER ====================
def read_potentiometer(adc):
    """Read potentiometer value and convert to 0-255 brightness"""
    try:
        pot_raw = adc.read_adc(POT_PIN)  # 0-1023
        brightness = int((pot_raw / 1023.0) * 255)
        return pot_raw, brightness
    except:
        return 0, 0

# ==================== LCD UPDATE ====================
def update_lcd(lcd, led_switch_on, auto_mode, lux_value):
    """Update LCD with current state"""
    try:
        lcd.clear()
        
        # Line 1: Switch states
        led_status = "ON " if led_switch_on else "OFF"
        mode_status = "AUTO" if auto_mode else "MAN"
        lcd.message = f"LED:{led_status} {mode_status}"
        
        # Line 2: Lux value
        lcd.cursor_position(0, 1)
        lcd.message = f"Lux: {lux_value:.1f}"
    except:
        pass

#MAIN ====================
def main():
    print("Initializing Lux Processor...")
    time.sleep(2)
    
    # Initialize LED strip
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(LED_PIN, GPIO.OUT)
    GPIO.setup(SWITCH_LED_ONOFF, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(SWITCH_AUTO_MANUAL, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    pwm = GPIO.PWM(LED_PIN, PWM_FREQ)
    pwm.start(0)

    # Initialize I2C LCD
    i2c = busio.I2C(board.SCL, board.SDA)
    lcd = character_lcd.Character_LCD_I2C(i2c, LCD_COLS, LCD_ROWS, LCD_I2C_ADDRESS)
    lcd.clear()
    lcd.message = "Initializing..."
    time.sleep(1)
    
    # Initialize ADC for potentiometer
    try:
        from Adafruit_MCP3008 import MCP3008
        adc = MCP3008(spi=MCP3008.SPI.SpiDev(0, 0))
    except:
        adc = None
        print("Warning: ADC not available")
    
    # Initialize filter
    if ACTIVE_FILTER == 'sma':
        filter_obj = SMAFilter(11)
    elif ACTIVE_FILTER == 'ema':
        filter_obj = EMAFilter(0.1)
    else:  # 'sg'
        filter_obj = SGFilter(11, 3)
    
    # Calibration buffer
    calib_buffer = CircularBuffer(WINDOW_SIZE)
    
    # Bounds tracking
    min_lux = 0.0
    max_lux = 1000.0
    
    # Serial connection
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=5.0)
        time.sleep(2)  # Let connection stabilize
        ser.flush()
    except serial.SerialException as e:
        print(f"Failed to open serial port: {e}")
        return

    print(f"Listening on {SERIAL_PORT} @ {BAUD_RATE} baud...")
    print(f"Active filter: {ACTIVE_FILTER}")
    print("Ready to receive data!\n")

    # Display variables
    last_lux = 0.0
    last_lcd_update = 0
    LCD_UPDATE_INTERVAL = 0.5
    
    try:
        while True:
            current_time = time.time()

            # Read switches (LOW = ON with pull-up)
            led_switch_on = GPIO.input(SWITCH_LED_ONOFF) == GPIO.LOW
            auto_mode = GPIO.input(SWITCH_AUTO_MANUAL) == GPIO.LOW

            
            #if autoMode true run below
            if auto_mode:
                try:
                    if ser.in_waiting > 0:
                        packet = ser.readline().decode('utf-8').strip()
                    else:
                        continue
                
                    # Parse: timestamp,lux1,lux2
                    parts = packet.split(',')
                    if len(parts) != 3:
                        continue
                
                    timestamp = int(parts[0])
                    lux1 = float(parts[1])
                    lux2 = float(parts[2])
                    raw_lux = (lux1 + lux2) / 2.0
                
                    # Apply filter
                    filtered = filter_obj.process(raw_lux)
                
                    # Add to calibration buffer
                    calib_buffer.add(filtered)
                
                    # Compute robust bounds
                    if calib_buffer.is_full():
                        data_array = calib_buffer.get_array()
                        new_min, new_max = compute_robust_bounds(data_array)
                    
                        # Smooth blending
                        min_lux = (1.0 - BOUNDS_ALPHA) * min_lux + BOUNDS_ALPHA * new_min
                        max_lux = (1.0 - BOUNDS_ALPHA) * max_lux + BOUNDS_ALPHA * new_max
                    
                        # Ensure sensible span
                        if max_lux <= min_lux + 1e-3:
                            max_lux = min_lux + 1.0
                
                    # Map to LED brightness
                    brightness = map_to_led(filtered, min_lux, max_lux)
                
                    # Set all LEDs to this brightness (white color)
                    duty_cycle = (brightness / 255.0) * 100.0  # Convert 0-255 to 0-100%
                    #if on switch then map vals onto led
                    if led_switch_on:
                        pwm.ChangeDutyCycle(duty_cycle)
                    else:
                        pwm.ChangeDutyCycle(0)
                    
                    # Print status
                    print(f"Raw: {raw_lux:6.2f} | Filt: {filtered:6.2f} | "
                          f"Min: {min_lux:6.2f} | Max: {max_lux:6.2f} | "
                          f"LED: {brightness:3d}")
                except Exception as e:
                    print(f"Error processing packet: {e}")
                    continue
            else:
                # MANUAL MODE
                if adc:
                    pot_raw, brightness = read_potentiometer(adc)
                    last_lux = pot_raw  # Store for LCD display
                    print(f"MANUAL | Pot: {last_lux:4d} | Brightness: {brightness:3d}")
                else:
                    brightness = 0
                
                # Determine final value based on LED switch
                if led_switch_on:
                    final_brightness = brightness
                else:
                    final_brightness = 0
                
                # Apply to LED
                duty_cycle = (final_brightness / 255.0) * 100.0
                pwm.ChangeDutyCycle(duty_cycle)
            
            if current_time - last_lcd_update >= LCD_UPDATE_INTERVAL:
                update_lcd(lcd, led_switch_on, auto_mode, last_lux)
                last_lcd_update = current_time

            time.sleep(0.05)

    except KeyboardInterrupt:
        print("\nShutting down...")
        lcd.clear()
        lcd.message = "Shutdown..."
        pwm.ChangeDutyCycle(0)
        pwm.stop()
        GPIO.cleanup()
        ser.close()

if __name__ == "__main__":
    main()