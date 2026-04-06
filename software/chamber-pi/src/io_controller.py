import serial
import spidev
import RPi.GPIO as GPIO

from config import (
    SWITCH1_PIN, SWITCH2_PIN, PWM_PIN,
    SPI_PORT, SPI_DEVICE, POT_CHANNEL,
    UART_PORT, UART_BAUD,
    PWM_FREQ, MAX_PWM_VALUE,
    LUX_BUFFER_SIZE
)


class IOController:
    def __init__(self):
        # State variables
        self.sw1 = False
        self.sw2 = False
        self.pot_value = 0.0
        self.lux_value = 0

        # Bounds buffer (1 minute of lux history)
        self.lux_buffer = [0] * LUX_BUFFER_SIZE
        self.buffer_index = 0
        self.buffer_count = 0
        self.live_min = 0
        self.live_max = 0

        # Hardware handles
        self.spi = None
        self.serial = None
        self.pwm = None
        self.spi_available = False
        self.serial_available = False

    def begin(self):
        """Initialize all hardware peripherals."""
        # GPIO setup
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(SWITCH1_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(SWITCH2_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(PWM_PIN, GPIO.OUT)

        # PWM setup (software PWM, hardware PWM requires pigpio)
        self.pwm = GPIO.PWM(PWM_PIN, PWM_FREQ)
        self.pwm.start(0)

        # SPI setup for MCP3008 ADC
        self.spi = spidev.SpiDev()
        try:
            self.spi.open(SPI_PORT, SPI_DEVICE)
            self.spi.max_speed_hz = 1000000
            self.spi_available = True
        except FileNotFoundError:
            print("WARNING: SPI device not found. Analog input disabled.")
            self.spi_available = False
        except OSError as e:
            print(f"WARNING: Unable to open SPI device: {e}. Analog input disabled.")
            self.spi_available = False

        # UART setup
        try:
            self.serial = serial.Serial(UART_PORT, UART_BAUD, timeout=0.1)
            self.serial_available = True
        except Exception as e:
            print(f"WARNING: Unable to open UART {UART_PORT}: {e}. Lux serial input disabled.")
            self.serial = None
            self.serial_available = False

        print("==================")
        print("   System Ready   ")
        print("==================")

    def update(self):
        """Update all input states."""
        self._read_switches()
        self._read_analog()
        self._read_uart()

    def _read_switches(self):
        """Read switch states (pull-up: HIGH = released)."""
        self.sw1 = GPIO.input(SWITCH1_PIN)
        self.sw2 = GPIO.input(SWITCH2_PIN)

    def _read_analog(self):
        """Read potentiometer via MCP3008 ADC."""
        if not self.spi_available or self.spi is None:
            self.pot_value = 0.0
            return

        try:
            adc = self.spi.xfer2([1, (8 + POT_CHANNEL) << 4, 0])
            raw = ((adc[1] & 3) << 8) + adc[2]
            self.pot_value = raw / 1023.0
        except Exception as e:
            print(f"WARNING: SPI read failed: {e}")
            self.pot_value = 0.0

    def _read_uart(self):
        """Read lux value from UART."""
        if not self.serial_available or self.serial is None:
            return

        try:
            if self.serial.in_waiting > 0:
                line = self.serial.readline().decode('utf-8').strip()
                if line:
                    self.lux_value = int(float(line))
        except (ValueError, UnicodeDecodeError):
            pass
        except Exception as e:
            print(f"WARNING: UART read failed: {e}")

    def set_pwm(self, value):
        """Set PWM duty cycle (0-1023 maps to 0-100%)."""
        duty = (value / MAX_PWM_VALUE) * 100.0
        duty = max(0.0, min(100.0, duty))
        self.pwm.ChangeDutyCycle(duty)

    def get_switch1(self):
        return self.sw1

    def get_switch2(self):
        return self.sw2

    def get_analog_value(self):
        return self.pot_value

    def get_lux_value(self):
        return self.lux_value

    def _update_bounds(self):
        """Recalculate min/max from buffer."""
        if self.buffer_count == 0:
            return

        self.live_min = self.lux_buffer[0]
        self.live_max = self.lux_buffer[0]
        for i in range(1, self.buffer_count):
            if self.lux_buffer[i] < self.live_min:
                self.live_min = self.lux_buffer[i]
            if self.lux_buffer[i] > self.live_max:
                self.live_max = self.lux_buffer[i]

    def get_clamped_lux(self, raw_lux):
        """Get lux clamped to 1-minute bounds."""
        self.lux_buffer[self.buffer_index] = raw_lux
        self.buffer_index = (self.buffer_index + 1) % LUX_BUFFER_SIZE
        if self.buffer_count < LUX_BUFFER_SIZE:
            self.buffer_count += 1

        self._update_bounds()

        if self.buffer_count < LUX_BUFFER_SIZE:
            return raw_lux

        if raw_lux < self.live_min:
            return self.live_min
        if raw_lux > self.live_max:
            return self.live_max
        return raw_lux

    def to_string(self):
        """Return string representation for debugging."""
        sw1_str = "HIGH" if self.sw1 else "LOW "
        sw2_str = "HIGH" if self.sw2 else "LOW "
        return (f"[Switches] S1={sw1_str} S2={sw2_str} | "
                f"[Analog] {self.pot_value:.3f} | "
                f"[Lux] {self.lux_value}")

    def cleanup(self):
        """Cleanup GPIO and peripherals."""
        if self.pwm:
            self.pwm.stop()
        if self.spi and self.spi_available:
            try:
                self.spi.close()
            except Exception:
                pass
        if self.serial:
            try:
                self.serial.close()
            except Exception:
                pass
        GPIO.cleanup()
