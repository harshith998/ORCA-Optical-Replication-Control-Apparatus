"""
RS-485 / wired UART receiver for chamber-pi.

The satellite firmware transmits ASCII packets over RS-485 (UART at 115200 baud)
whenever the SNS line is pulled low (cable connected).  On the Pi side:
  - RJ45_SNS_PIN (BCM 18): software pull-up; cable grounds it → reads LOW = connected
  - UART RX     (BCM 15): hardware UART RX on /dev/serial0

Packet format (single newline-terminated line sent by rs_transciever.c):
  START sample_count:N,f1:N,f2:N,fz:N,f3:N,f4:N,f5:N,fy:N,f6:N,fxl:N,f7:N,f8:N,nir:N,clear:N,gps_valid:N,lat:F,lon:F,time:N END
"""

import re
import serial
import RPi.GPIO as GPIO

from config import RJ45_SNS_PIN, RS_UART_DEVICE, RS_RX_BAUD

_INT_FIELDS = {
    'sample_count', 'f1', 'f2', 'fz', 'f3', 'f4', 'f5',
    'fy', 'f6', 'fxl', 'f7', 'f8', 'nir', 'clear',
    'gps_valid', 'time',
}
_FLOAT_FIELDS = {'lat', 'lon'}
_ALL_FIELDS = _INT_FIELDS | _FLOAT_FIELDS

# Matches START...END on a single line; no \n required (handles hangup before \n arrives)
_PACKET_RE = re.compile(rb'START\s+([^\r\n]+)\s+END')


def _parse_line(line: str) -> dict | None:
    """Parse a single 'START ... END' ASCII line into a decoded packet dict.

    Returns the same structure as lora_receiver.decode_packet, or None on error.
    """
    line = line.strip()
    m = re.match(r'^START\s+(.+?)\s+END$', line)
    if not m:
        return None

    fields: dict = {}
    for pair in m.group(1).split(','):
        if ':' not in pair:
            return None
        key, _, val = pair.partition(':')
        key = key.strip()
        val = val.strip()
        try:
            if key in _FLOAT_FIELDS:
                fields[key] = float(val)
            elif key in _INT_FIELDS:
                fields[key] = int(val)
        except ValueError:
            return None

    if not _ALL_FIELDS.issubset(fields):
        return None

    return {
        'sample_count': fields['sample_count'],
        'channels': {
            'f1':    fields['f1'],
            'f2':    fields['f2'],
            'fz':    fields['fz'],
            'f3':    fields['f3'],
            'f4':    fields['f4'],
            'f5':    fields['f5'],
            'fy':    fields['fy'],
            'f6':    fields['f6'],
            'fxl':   fields['fxl'],
            'f7':    fields['f7'],
            'f8':    fields['f8'],
            'nir':   fields['nir'],
            'clear': fields['clear'],
        },
        'gps': {
            'valid':     bool(fields['gps_valid']),
            'latitude':  fields['lat'],
            'longitude': fields['lon'],
            'unix_time': fields['time'],
        },
    }


class RS485Receiver:
    """Manages the RJ45 sense pin and UART port for wired RS-485 reception."""

    def __init__(self):
        self._ser = None
        self._buf = b''
        self.status = 'Not initialized'
        self.hardware_ready = False

    def begin(self):
        """Set up the SNS GPIO input (software pull-up) and open the serial port."""
        try:
            # Pull-up: idle HIGH; cable grounds to LOW → connected
            GPIO.setup(RJ45_SNS_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            self.status = f'OK - SNS on BCM{RJ45_SNS_PIN} (pull-up, LOW = connected)'
            self.hardware_ready = True
        except Exception as exc:
            self.status = f'Unavailable - SNS GPIO init failed: {exc}'
            return

        try:
            self._ser = serial.Serial(
                port=RS_UART_DEVICE,
                baudrate=RS_RX_BAUD,
                timeout=0,   # non-blocking
                dsrdtr=False,
                rtscts=False,
            )
            self.status += f'; UART {RS_UART_DEVICE} @ {RS_RX_BAUD} baud'
        except Exception as exc:
            self._ser = None
            self.status += f'; UART unavailable: {exc}'
            print(f'[RS485] Failed to open {RS_UART_DEVICE}: {exc}')


    def is_connected(self) -> bool:
        """Return True when the sense pin reads LOW (cable grounded)."""
        if not self.hardware_ready:
            return False
        return GPIO.input(RJ45_SNS_PIN) == GPIO.LOW

    def poll(self) -> dict | None:
        """Read available bytes from the UART, buffer them, and return a decoded
        packet dict if a complete START...END frame is available."""
        if self._ser is None or not self._ser.is_open:
            return None
        try:
            chunk = self._ser.read(4096)
            if chunk:
                self._buf += chunk
        except serial.SerialException:
            # Hangup fires when the ESP32 de-asserts RS485 EN and deep-sleeps.
            # Don't close/reopen — that resets udev permissions. The PL011
            # self-recovers on the next transmission without any intervention.
            pass

        # Cap buffer to prevent unbounded growth from boot noise
        if len(self._buf) > 8192:
            self._buf = self._buf[-4096:]

        # Search for a complete START...END frame without requiring \n.
        # The final \n is often the byte that triggers the hangup, so we
        # match on the self-delimiting START...END markers instead.
        m = _PACKET_RE.search(self._buf)
        if m:
            decoded = m.group(0).decode('ascii', errors='replace')
            self._buf = self._buf[m.end():]
            print(f'[RS485] Parsing line: {decoded!r}')
            return _parse_line(decoded)

        return None

    def close(self):
        if self._ser and self._ser.is_open:
            try:
                self._ser.close()
            except Exception:
                pass
