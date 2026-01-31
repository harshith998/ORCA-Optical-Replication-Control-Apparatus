"""
Mock hardware modules for testing chamber-pi without Raspberry Pi.
These simulate GPIO, SPI, Serial, and I2C interfaces.
"""

import sys
from unittest.mock import MagicMock


class MockGPIO:
    """Mock RPi.GPIO module."""
    BCM = 11
    OUT = 0
    IN = 1
    PUD_UP = 22
    HIGH = 1
    LOW = 0

    _pin_states = {}
    _pin_modes = {}

    @classmethod
    def setmode(cls, mode):
        pass

    @classmethod
    def setwarnings(cls, state):
        pass

    @classmethod
    def setup(cls, pin, mode, pull_up_down=None):
        cls._pin_modes[pin] = mode
        cls._pin_states[pin] = cls.HIGH if pull_up_down == cls.PUD_UP else cls.LOW

    @classmethod
    def input(cls, pin):
        return cls._pin_states.get(pin, cls.HIGH)

    @classmethod
    def output(cls, pin, state):
        cls._pin_states[pin] = state

    @classmethod
    def cleanup(cls):
        cls._pin_states.clear()
        cls._pin_modes.clear()

    @classmethod
    def set_pin(cls, pin, state):
        """Test helper to set pin state."""
        cls._pin_states[pin] = state

    class PWM:
        def __init__(self, pin, freq):
            self.pin = pin
            self.freq = freq
            self.duty = 0

        def start(self, duty):
            self.duty = duty

        def ChangeDutyCycle(self, duty):
            self.duty = duty

        def stop(self):
            self.duty = 0


class MockSpiDev:
    """Mock spidev.SpiDev module."""
    def __init__(self):
        self.port = None
        self.device = None
        self.max_speed_hz = 0
        self._adc_value = 512  # Default mid-range

    def open(self, port, device):
        self.port = port
        self.device = device

    def xfer2(self, data):
        # Simulate MCP3008 ADC response
        # Returns 10-bit value split across bytes
        high = (self._adc_value >> 8) & 0x03
        low = self._adc_value & 0xFF
        return [0, high, low]

    def close(self):
        pass

    def set_adc_value(self, value):
        """Test helper to set ADC value (0-1023)."""
        self._adc_value = max(0, min(1023, value))


class MockSerial:
    """Mock serial.Serial module."""
    def __init__(self, port=None, baudrate=9600, timeout=None):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._buffer = []
        self._is_open = True

    @property
    def in_waiting(self):
        return len(self._buffer)

    def readline(self):
        if self._buffer:
            return self._buffer.pop(0).encode('utf-8')
        return b''

    def close(self):
        self._is_open = False

    def add_data(self, line):
        """Test helper to add data to serial buffer."""
        self._buffer.append(line + '\n')


class MockSMBus:
    """Mock smbus2.SMBus module."""
    def __init__(self, bus=1):
        self.bus = bus
        self._data = {}

    def write_byte(self, address, data):
        self._data[address] = data

    def read_byte(self, address):
        return self._data.get(address, 0)

    def close(self):
        pass


def install_mocks():
    """Install mock modules into sys.modules."""
    # Create mock modules
    mock_rpi = MagicMock()
    mock_rpi.GPIO = MockGPIO

    sys.modules['RPi'] = mock_rpi
    sys.modules['RPi.GPIO'] = MockGPIO

    # Mock spidev
    mock_spidev = MagicMock()
    mock_spidev.SpiDev = MockSpiDev
    sys.modules['spidev'] = mock_spidev

    # Mock serial
    mock_serial_module = MagicMock()
    mock_serial_module.Serial = MockSerial
    sys.modules['serial'] = mock_serial_module

    # Mock smbus2
    mock_smbus = MagicMock()
    mock_smbus.SMBus = MockSMBus
    sys.modules['smbus2'] = mock_smbus

    return {
        'GPIO': MockGPIO,
        'SpiDev': MockSpiDev,
        'Serial': MockSerial,
        'SMBus': MockSMBus
    }