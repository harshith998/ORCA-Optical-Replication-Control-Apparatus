import RPi.GPIO as GPIO

from config import (
    SWITCH1_PIN, SWITCH2_PIN, PWM_PIN,
    LORA_SPI_PORT, LORA_SPI_DEVICE, LORA_NRESET_PIN, LORA_BUSY_PIN, LORA_DIO1_PIN,
    LORA_FREQ_MHZ, LORA_BW_KHZ, LORA_SF, LORA_CR, LORA_SYNC_WORD,
    PWM_FREQ, MAX_PWM_VALUE,
    LUX_BUFFER_SIZE,
    SOLENOID_PIN
)
from lora_receiver import LoRaReceiver, decode_packet, PACKET_SIZE


class IOController:
    def __init__(self):
        # State variables
        self.sw1 = True
        self.sw2 = True
        self.lux_value = 0

        # Bounds buffer (1 minute of lux history)
        self.lux_buffer = [0] * LUX_BUFFER_SIZE
        self.buffer_index = 0
        self.buffer_count = 0
        self.live_min = 0
        self.live_max = 0

        # Hardware handles
        self.lora = None
        self.pwm = None

        # Last decoded LoRa packet (full spectral + GPS data)
        self.last_packet = None

        # All 13 spectral channels from the last packet (keyed by channel name)
        self.spectral_channels = {}

        # Last GPS fix from the last packet
        self.last_gps = {'valid': False, 'latitude': 0.0, 'longitude': 0.0, 'unix_time': 0}

        # Init / diagnostics
        self.status = {
            'gpio': 'Not initialized',
            'pwm': 'Not initialized',
            'lora': 'Not initialized',
            'solenoid': 'Not initialized',
        }
        self.hardware_ready = {
            'gpio': False,
            'pwm': False,
            'lora': False,
            'solenoid': False,
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
            GPIO.setup(SOLENOID_PIN, GPIO.OUT, initial=GPIO.LOW)
            self.status['gpio'] = (
                f"OK - GPIO ready (S1=BCM{SWITCH1_PIN}, S2=BCM{SWITCH2_PIN}, PWM=BCM{PWM_PIN}, SOL=BCM{SOLENOID_PIN})"
            )
            self.hardware_ready['gpio'] = True
            self.hardware_ready['solenoid'] = True
            self.status['solenoid'] = f"OK - Solenoid on BCM{SOLENOID_PIN}, initially CLOSED"
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

        # LoRa setup (SX1262 on spidev0.1 / CE1)
        try:
            self.lora = LoRaReceiver(
                spi_port=LORA_SPI_PORT,
                spi_device=LORA_SPI_DEVICE,
                reset_pin=LORA_NRESET_PIN,
                busy_pin=LORA_BUSY_PIN,
                dio1_pin=LORA_DIO1_PIN,
            )
            self.lora.begin(
                freq_mhz=LORA_FREQ_MHZ,
                bw_khz=LORA_BW_KHZ,
                sf=LORA_SF,
                cr=LORA_CR,
                sync_word=LORA_SYNC_WORD,
            )
            self.status['lora'] = (
                f"OK - SX1262 receiving at {LORA_FREQ_MHZ} MHz "
                f"BW{LORA_BW_KHZ} SF{LORA_SF} CR4/{LORA_CR} sync=0x{LORA_SYNC_WORD:02X}"
            )
            self.hardware_ready['lora'] = True
        except Exception as exc:
            self.lora = None
            self.status['lora'] = f"Unavailable - LoRa init failed: {exc}"

        print("==================")
        print(" Init Diagnostics ")
        print("==================")
        for name in ('gpio', 'pwm', 'lora', 'solenoid'):
            print(f"{name.upper():>4}: {self.status[name]}")

    def update(self):
        """Update all input states."""
        self._read_switches()
        self._read_lora()

    def _read_switches(self):
        """Read switch states (pull-up: HIGH = released)."""
        if not self.hardware_ready['gpio']:
            self.sw1 = True
            self.sw2 = True
            return
        self.sw1 = GPIO.input(SWITCH1_PIN)
        self.sw2 = GPIO.input(SWITCH2_PIN)

    def _read_lora(self):
        """Poll SX1262 for a received packet and decode it."""
        if not self.hardware_ready['lora'] or self.lora is None:
            return
        try:
            raw = self.lora.poll()
            if raw is None:
                return
            if raw == b'':
                print("[LoRa] CRC error — packet discarded")
                return
            print(f"[LoRa] Packet received: {len(raw)} bytes | hex: {raw.hex()}")
            packet = decode_packet(raw)
            if packet is None:
                print(f"[LoRa] Decode failed: got {len(raw)} bytes, expected {PACKET_SIZE}")
                return
            self.last_packet = packet
            self.spectral_channels = packet['channels']
            self.lux_value = packet['channels']['clear']
            self.last_gps = packet['gps']
            print(f"[LoRa] Decoded: sample={packet['sample_count']} clear={packet['channels']['clear']} gps_valid={packet['gps']['valid']}")
        except Exception as exc:
            print(f"[LoRa] Exception in _read_lora: {exc}")

    def set_pwm(self, value):
        """Set PWM duty cycle (0-1023 maps to 0-100%)."""
        if not self.hardware_ready['pwm'] or self.pwm is None:
            return
        duty = 100.0 - (value / MAX_PWM_VALUE) * 100.0
        duty = max(0.0, min(100.0, duty))
        self.pwm.ChangeDutyCycle(duty)

    def set_solenoid(self, on: bool):
        """Open (True) or close (False) the solenoid valve."""
        if not self.hardware_ready['solenoid']:
            return
        GPIO.output(SOLENOID_PIN, GPIO.HIGH if on else GPIO.LOW)

    def get_switch1(self):
        return self.sw1

    def get_switch2(self):
        return self.sw2

    def get_lux_value(self):
        return self.lux_value

    def get_spectral_channels(self) -> dict:
        return dict(self.spectral_channels)

    def get_last_gps(self) -> dict:
        return dict(self.last_gps)

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
                f"[Lux] {self.lux_value}")

    def cleanup(self):
        """Cleanup GPIO and peripherals."""
        if self.pwm:
            try:
                self.pwm.stop()
            except Exception:
                pass
        if self.lora:
            try:
                self.lora.close()
            except Exception:
                pass
        try:
            GPIO.cleanup()
        except Exception:
            pass
