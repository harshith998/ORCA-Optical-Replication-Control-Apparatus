import RPi.GPIO as GPIO

from config import (
    SWITCH1_PIN, SWITCH2_PIN, PWM_PIN,
    LORA_SPI_PORT, LORA_SPI_DEVICE, LORA_NRESET_PIN, LORA_BUSY_PIN, LORA_DIO1_PIN,
    LORA_FREQ_MHZ, LORA_BW_KHZ, LORA_SF, LORA_CR, LORA_SYNC_WORD,
    PWM_FREQ, MAX_PWM_VALUE,
    LUX_BUFFER_SIZE,
    SOLENOID_PIN,
    LED_GRN_PIN, LED_YLW_PIN,
)
from lora_receiver import LoRaReceiver, decode_packet, PACKET_SIZE
from rs_receiver import RS485Receiver


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

        # Frozen per-minute snapshot used for clamping (updated once per full window)
        self.frozen_min = 0
        self.frozen_max = 0
        self._samples_since_freeze = 0

        # Hardware handles
        self.lora = None
        self.pwm = None
        self.rs = RS485Receiver()

        # YLW LED flash counter: set to N on packet receipt, decremented each update
        self._ylw_flash_ticks = 0

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
            'rs485': 'Not initialized',
            'leds': 'Not initialized',
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
            # BCM 14 = UART TX: skip GPIO.setup so it stays in ALT0 (UART) mode.
            # SW1 is not used for control logic; default to released (True).
            GPIO.setup(SWITCH2_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(PWM_PIN, GPIO.OUT)
            GPIO.setup(SOLENOID_PIN, GPIO.OUT, initial=GPIO.LOW)
            self.status['gpio'] = (
                f"OK - GPIO ready (S1=BCM{SWITCH1_PIN} skipped/UART-TX, S2=BCM{SWITCH2_PIN}, PWM=BCM{PWM_PIN}, SOL=BCM{SOLENOID_PIN})"
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

        # Indicator LED setup (GRN = wired connected, YLW = RS-485 activity)
        if self.hardware_ready['gpio']:
            try:
                GPIO.setup(LED_GRN_PIN, GPIO.OUT, initial=GPIO.LOW)
                GPIO.setup(LED_YLW_PIN, GPIO.OUT, initial=GPIO.LOW)
                self.status['leds'] = (
                    f'OK - GRN=BCM{LED_GRN_PIN} (wired link), YLW=BCM{LED_YLW_PIN} (RS-485 activity)'
                )
            except Exception as exc:
                self.status['leds'] = f'Unavailable - LED init failed: {exc}'
        else:
            self.status['leds'] = 'Skipped - GPIO not available'

        # RS-485 / wired UART setup (SNS sense pin + /dev/serial0)
        self.rs.begin()
        self.status['rs485'] = self.rs.status

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
        for name in ('gpio', 'pwm', 'lora', 'solenoid', 'rs485', 'leds'):
            print(f"{name.upper():>6}: {self.status[name]}")

    def update(self):
        """Update all input states."""
        self._read_switches()

        # Prefer wired RS-485 when a cable is detected, mirroring the firmware
        # path: is_connected() → rs485_send, else → LoRa.
        wired = self.rs.is_connected()
        print(f'[IO] wired={wired} hw_ready={self.rs.hardware_ready} ser={self.rs._ser is not None}')
        if wired:
            self._read_rs485()
        else:
            self._read_lora()

        self._update_leds()

    def _update_leds(self):
        """Drive indicator LEDs based on connection and activity state."""
        if not self.hardware_ready.get('gpio'):
            return
        try:
            # GRN: solid on when RJ45 cable is plugged in
            GPIO.output(LED_GRN_PIN, GPIO.HIGH if self.rs.is_connected() else GPIO.LOW)

            # YLW: flashes for ~500 ms after each RS-485 packet is received
            if self._ylw_flash_ticks > 0:
                self._ylw_flash_ticks -= 1
                GPIO.output(LED_YLW_PIN, GPIO.HIGH)
            else:
                GPIO.output(LED_YLW_PIN, GPIO.LOW)
        except Exception as exc:
            print(f'[LED] Output error: {exc}')

    def _read_switches(self):
        """Read switch states (pull-up: HIGH = released)."""
        if not self.hardware_ready['gpio']:
            self.sw1 = True
            self.sw2 = True
            return
        self.sw1 = True  # BCM 14 = UART TX; not configured as GPIO — default released
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

    def _read_rs485(self):
        """Poll the RS-485 UART for a complete packet and decode it."""
        packet = self.rs.poll()
        if packet is None:
            return
        print(f'[RS485] Packet received: sample={packet["sample_count"]} '
              f'clear={packet["channels"]["clear"]} gps_valid={packet["gps"]["valid"]}')
        self.last_packet = packet
        self.spectral_channels = packet['channels']
        self.lux_value = packet['channels']['clear']
        self.last_gps = packet['gps']
        # Trigger YLW flash for ~500 ms (5 ticks at 100 ms loop rate)
        self._ylw_flash_ticks = 5

    def is_wired_connected(self) -> bool:
        """Return True when a cable is detected on the RJ45 sense pin."""
        return self.rs.is_connected()

    def set_pwm(self, value):
        """Set PWM duty cycle (0-1023 maps to 0-100%)."""
        if not self.hardware_ready['pwm'] or self.pwm is None:
            return
        duty = (value / MAX_PWM_VALUE) * 100.0
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
        """Get lux clamped to the previous minute's frozen bounds.

        The accumulation buffer fills for one full window (LUX_BUFFER_SIZE samples).
        When it completes, live min/max are computed and frozen. Clamping uses the
        frozen snapshot so bounds only shift once per minute, and never include the
        value currently being clamped.
        """
        # Accumulate into buffer
        self.lux_buffer[self.buffer_index] = raw_lux
        self.buffer_index = (self.buffer_index + 1) % LUX_BUFFER_SIZE
        if self.buffer_count < LUX_BUFFER_SIZE:
            self.buffer_count += 1

        self._samples_since_freeze += 1

        # Freeze a new snapshot once per full window
        if self._samples_since_freeze >= LUX_BUFFER_SIZE:
            self._update_bounds()
            self.frozen_min = self.live_min
            self.frozen_max = self.live_max
            self._samples_since_freeze = 0

        # No frozen snapshot yet — pass through unclamped
        if self.buffer_count < LUX_BUFFER_SIZE:
            return raw_lux

        if raw_lux < self.frozen_min:
            return self.frozen_min
        if raw_lux > self.frozen_max:
            return self.frozen_max
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
            self.rs.close()
        except Exception:
            pass
        try:
            GPIO.cleanup()
        except Exception:
            pass
