#!/usr/bin/env python3
import serial
import time
import numpy as np
from collections import deque
from scipy import linalg
import RPi.GPIO as GPIO
import Adafruit_CharLCD as LCD

# LED Configuration
LED_PIN = 18  # GPIO 18 (PWM capable)
PWM_FREQ = 5000  # 5kHz like Arduino

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

#MAIN ====================
def main():
    print("Initializing Lux Processor...")
    
    # Initialize LED strip
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(LED_PIN, GPIO.OUT)
    pwm = GPIO.PWM(LED_PIN, PWM_FREQ)
    pwm.start(0)
    
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
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=5.0)
    ser.flush()  # Clear any existing data

    print(f"Listening on {SERIAL_PORT} @ {BAUD_RATE} baud...")
    print(f"Active filter: {ACTIVE_FILTER}")
    print("Ready to receive data!\n")
    
    try:
        while True:
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
                pwm.ChangeDutyCycle(duty_cycle)
                
                # Print status
                print(f"Raw: {raw_lux:6.2f} | Filt: {filtered:6.2f} | "
                      f"Min: {min_lux:6.2f} | Max: {max_lux:6.2f} | "
                      f"LED: {brightness:3d}")
            except Exception as e:
                print(f"Error processing packet: {e}")
                continue
    
    except KeyboardInterrupt:
        print("\nShutting down...")
        pwm.ChangeDutyCycle(0)
        pwm.stop()
        GPIO.cleanup()
        ser.close()

if __name__ == "__main__":
    main()