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
        self.sw1 = True
        self.sw2 = True
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

        # Init / diagnostics
        self.status = {
            'gpio': 'Not initialized',
            'pwm': 'Not initialized',
            'spi': 'Not initialized',
            'uart': 'Not initialized',
        }
        self.hardware_ready = {
            'gpio': False,
            'pwm': False,
            'spi': False,
            'uart': False,
        }

    def begin(self):
        """Initialize all hardware peripherals without crashing if optional hardware is absent."""
        # GPIO setup
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(SWITCH1_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(SWITCH2_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(PWM_PIN, GPIO.OUT)
            self.status['gpio'] = (
                f"OK - GPIO ready (S1=BCM{SWITCH1_PIN}, S2=BCM{SWITCH2_PIN}, PWM=BCM{PWM_PIN})"
            )
            self.hardware_ready['gpio'] = True
        except Exception as exc:
            self.status['gpio'] = f"Unavailable - GPIO init failed: {exc}"

        # PWM setup
        if self.hardware_ready['gpio']:
            try:
                self.pwm = GPIO.PWM(PWM_PIN, PWM_FREQ)
                self.pwm.start(0)
                self.status['pwm'] = f"OK - PWM started on BCM{PWM_PIN} at {PWM_FREQ} Hz"
                self.hardware_ready['pwm'] = True
            except Exception as exc:
                self.status['pwm'] = f"Unavailable - PWM init failed: {exc}"
        else:
            self.status['pwm'] = 'Skipped - GPIO not available'

        # SPI setup
        try:
            self.spi = spidev.SpiDev()
            self.spi.open(SPI_PORT, SPI_DEVICE)
            self.spi.max_speed_hz = 1000000
            self.status['spi'] = (
                f"OK - SPI bus /dev/spidev{SPI_PORT}.{SPI_DEVICE} opened; external device not verified"
            )
            self.hardware_ready['spi'] = True
        except FileNotFoundError:
            self.spi = None
            self.status['spi'] = (
                f"Missing - /dev/spidev{SPI_PORT}.{SPI_DEVICE} not found. Enable SPI if you plan to use it"
            )
        except Exception as exc:
            self.spi = None
            self.status['spi'] = f"Unavailable - SPI open failed: {exc}"

        # UART setup
        try:
            self.serial = serial.Serial(UART_PORT, UART_BAUD, timeout=0.1)
            self.status['uart'] = (
                f"OK - UART port {UART_PORT} opened at {UART_BAUD} baud; external sender not verified"
            )
            self.hardware_ready['uart'] = True
        except FileNotFoundError:
            self.serial = None
            self.status['uart'] = f"Missing - UART device {UART_PORT} not found"
        except Exception as exc:
            self.serial = None
            self.status['uart'] = f"Unavailable - UART open failed: {exc}"

        print("==================")
        print(" Init Diagnostics ")
        print("==================")
        for name in ('gpio', 'pwm', 'spi', 'uart'):
            print(f"{name.upper():>4}: {self.status[name]}")

    def update(self):
        """Update all input states."""
        self._read_switches()
        self._read_analog()
        self._read_uart()

    def _read_switches(self):
        """Read switch states (pull-up: HIGH = released)."""
        if not self.hardware_ready['gpio']:
            self.sw1 = True
            self.sw2 = True
            return
        self.sw1 = GPIO.input(SWITCH1_PIN)
        self.sw2 = GPIO.input(SWITCH2_PIN)

    def _read_analog(self):
        """Read potentiometer via MCP3008 ADC when available; otherwise keep a safe default."""
        if not self.hardware_ready['spi'] or self.spi is None:
            self.pot_value = 0.0
            return
        try:
            adc = self.spi.xfer2([1, (8 + POT_CHANNEL) << 4, 0])
            raw = ((adc[1] & 3) << 8) + adc[2]
            self.pot_value = raw / 1023.0
        except Exception:
            # No verified SPI ADC present. Stay operational.
            self.pot_value = 0.0

    def _read_uart(self):
        """Read lux value from UART when available."""
        if not self.hardware_ready['uart'] or self.serial is None:
            return
        try:
            if self.serial.in_waiting > 0:
                line = self.serial.readline().decode('utf-8').strip()
                if line:
                    self.lux_value = int(float(line))
        except (ValueError, UnicodeDecodeError, OSError, serial.SerialException):
            pass

    def set_pwm(self, value):
        """Set PWM duty cycle (0-1023 maps to 0-100%)."""
        if not self.hardware_ready['pwm'] or self.pwm is None:
            return
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

    def get_init_report(self):
        return dict(self.status)

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
            try:
                self.pwm.stop()
            except Exception:
                pass
        if self.spi:
            try:
                self.spi.close()
            except Exception:
                pass
        if self.serial:
            try:
                self.serial.close()
            except Exception:
                pass
        try:
            GPIO.cleanup()
        except Exception:
            pass
