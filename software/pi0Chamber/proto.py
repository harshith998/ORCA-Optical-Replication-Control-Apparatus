import time
import sys
import serial

try:
    import RPi.GPIO as GPIO
except Exception as e:
    print("ERROR: RPi.GPIO not available:", e)
    sys.exit(1)

# --- Configuration ---------------------------------------------------------

# GPIO pins (BCM numbering)
SWITCH_PIN_1 = 17  # change as needed
SWITCH_PIN_2 = 27  # change as needed

# UART ports (adjust to your setup)
# Primary UART (TX on GPIO14) used for data
DATA_UART_PORT = "/dev/serial0"    # primary UART (TX -> GPIO14)

# Secondary hardware UART for IO (you must enable and map this to GPIO5 via device-tree overlay)
IO_UART_PORT = "/dev/ttyAMA1"     # example device — enable/configure in OS to route to GPIO5

BAUDRATE = 115200

# Loop timing
LOOP_DELAY = 0.05  # seconds


# --- Setup ---------------------------------------------------------------
GPIO.setmode(GPIO.BCM)
GPIO.setup(SWITCH_PIN_1, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(SWITCH_PIN_2, GPIO.IN, pull_up_down=GPIO.PUD_UP)

def open_serial(port, baud=BAUDRATE):
    try:
        s = serial.Serial(port, baudrate=baud, timeout=0)
        return s
    except Exception as e:
        print(f"Failed to open serial {port}: {e}")
        return None

io_uart = open_serial(IO_UART_PORT)
data_uart = open_serial(DATA_UART_PORT)


# --- Helpers -------------------------------------------------------------
def read_switch(pin):
    # Pull-up input: GPIO.HIGH when open/not-pressed, LOW when pressed (to GND)
    raw = GPIO.input(pin)
    pressed = (raw == GPIO.LOW)
    return pressed

def read_available(ser):
    # Non-blocking read of all available bytes, returns decoded string or bytes
    if ser is None:
        return None
    try:
        n = ser.in_waiting
        if n:
            data = ser.read(n)
            try:
                return data.decode("utf-8", errors="replace")
            except Exception:
                return data
        return None
    except Exception as e:
        # Serial port error (disconnected, etc.)
        print(f"Serial read error on {ser.port}: {e}")
        return None


# --- Main loop -----------------------------------------------------------
def main():
    print("Starting proto loop. Ctrl-C to exit.")
    try:
        while True:
            sw1 = read_switch(SWITCH_PIN_1)
            sw2 = read_switch(SWITCH_PIN_2)

            io_msg = read_available(io_uart)      # UART for IO (short control bytes/messages)
            data_msg = read_available(data_uart)  # UART for data stream

            # Replace these prints with whatever processing you need
            print(f"SW1={'PRESSED' if sw1 else 'RELEASED'}  SW2={'PRESSED' if sw2 else 'RELEASED'}", end='')

            if io_msg is not None:
                print(f"  IO_UART: {repr(io_msg)}", end='')

            if data_msg is not None:
                print(f"  DATA_UART: {repr(data_msg)}", end='')

            print()  # newline

            time.sleep(LOOP_DELAY)

    except KeyboardInterrupt:
        pass
    finally:
        print("Cleaning up GPIO and closing serial ports.")
        GPIO.cleanup()
        if io_uart is not None:
            try:
                io_uart.close()
            except Exception:
                pass
        if data_uart is not None:
            try:
                data_uart.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()