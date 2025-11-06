#!/usr/bin/env python3
import serial
import time
import RPi.GPIO as GPIO
import board
import busio
import adafruit_character_lcd.character_lcd_i2c as character_lcd

# LED Configuration
LED_PIN = 18  # GPIO 18 (PWM capable)
PWM_FREQ = 5000  # 5kHz

# LCD Configuration (I2C)
LCD_COLS = 16
LCD_ROWS = 2
LCD_I2C_ADDRESS = 0x27  # Common I2C address, might be 0x3F

# Switch Configuration
SWITCH_LED_ONOFF = 5   # GPIO pin for LED on/off switch
SWITCH_AUTO_MANUAL = 6  # GPIO pin for auto/manual switch

# Potentiometer Configuration
POT_PIN = 0  # ADC channel for potentiometer (MCP3008 CH0)

# Serial Configuration
SERIAL_PORT = '/dev/ttyUSB0'  # Or /dev/ttyAMA0 for GPIO UART
BAUD_RATE = 115200

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
        lcd.message = f"LED:{led_status} {mode_status}\n"
       
        # Line 2: Lux value
        lcd.message += f"Lux: {lux_value:.1f}"
    except Exception as e:
        print(f"LCD Error: {e}")

# ==================== MAIN ====================
def main():
    print("Initializing Simplified Lux Processor...")
    time.sleep(2)
   
    # Initialize GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(LED_PIN, GPIO.OUT)
    GPIO.setup(SWITCH_LED_ONOFF, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(SWITCH_AUTO_MANUAL, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    # Initialize PWM
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
   
    # Serial connection
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1.0)
        time.sleep(2)  # Let connection stabilize
        ser.flush()
    except serial.SerialException as e:
        print(f"Failed to open serial port: {e}")
        return

    print(f"Listening on {SERIAL_PORT} @ {BAUD_RATE} baud...")
    print("Ready!\n")

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

            brightness = 0
           
            if auto_mode:
                # AUTO MODE - Read from serial
                try:
                    if ser.in_waiting > 0:
                        packet = ser.readline().decode('utf-8').strip()
                       
                        # Parse: timestamp,lux1,lux2
                        parts = packet.split(',')
                        if len(parts) == 3:
                            lux1 = float(parts[1])
                            lux2 = float(parts[2])
                            avg_lux = (lux1 + lux2) / 2.0
                            last_lux = avg_lux
                           
                            # Simple mapping: assume 0-1000 lux range
                            brightness = int((avg_lux / 1000.0) * 255)
                            brightness = max(0, min(255, brightness))  # Clamp 0-255
                           
                            print(f"AUTO | Lux: {avg_lux:6.2f} | Brightness: {brightness:3d}")
               
                except Exception as e:
                    print(f"Error processing packet: {e}")
           
            else:
                # MANUAL MODE - Read from potentiometer
                if adc:
                    pot_raw, brightness = read_potentiometer(adc)
                    last_lux = pot_raw
                    print(f"MANUAL | Pot: {pot_raw:4d} | Brightness: {brightness:3d}")
                else:
                    brightness = 0
           
            # Apply LED switch
            if led_switch_on:
                duty_cycle = (brightness / 255.0) * 100.0
                pwm.ChangeDutyCycle(duty_cycle)
            else:
                pwm.ChangeDutyCycle(0)
           
            # Update LCD periodically
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