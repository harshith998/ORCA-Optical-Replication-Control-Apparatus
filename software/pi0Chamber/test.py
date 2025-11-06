import serial
import time

# Configure serial port (UART)
# On Raspberry Pi, UART is typically on /dev/ttyS0 or /dev/ttyAMA0
uart = serial.Serial(
    port='/dev/ttyS0',  # Serial port
    baudrate=115200,    # Baud rate
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
    bytesize=serial.EIGHTBITS,
    timeout=1
)

try:
    print("Starting UART reading... Press Ctrl+C to exit")
    while True:
        if uart.in_waiting > 0:
            data = uart.readline().decode('utf-8').rstrip()
            print(f"Received: {data}")
        time.sleep(0.01)  # Small delay to prevent CPU hogging

except KeyboardInterrupt:
    print("\nExiting program")
    uart.close()
except Exception as e:
    print(f"Error: {e}")
    uart.close()