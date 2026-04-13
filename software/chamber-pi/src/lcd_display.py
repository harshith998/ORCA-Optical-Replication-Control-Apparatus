import time

import smbus2

from config import I2C_BUS, LCD_I2C_ADDRESS, LCD_COLS, LCD_ROWS

# LCD commands
LCD_CLEARDISPLAY = 0x01
LCD_RETURNHOME = 0x02
LCD_ENTRYMODESET = 0x04
LCD_DISPLAYCONTROL = 0x08
LCD_FUNCTIONSET = 0x20
LCD_SETDDRAMADDR = 0x80

# Flags for display entry mode
LCD_ENTRYLEFT = 0x02

# Flags for display control
LCD_DISPLAYON = 0x04
LCD_CURSOROFF = 0x00
LCD_BLINKOFF = 0x00

# Flags for function set
LCD_4BITMODE = 0x00
LCD_2LINE = 0x08
LCD_5x8DOTS = 0x00

# Flags for backlight control
LCD_BACKLIGHT = 0x08
LCD_NOBACKLIGHT = 0x00

# Control bits
EN = 0b00000100
RW = 0b00000010
RS = 0b00000001


class LCDDisplay:
    def __init__(self, address=LCD_I2C_ADDRESS, cols=LCD_COLS, rows=LCD_ROWS):
        self.address = address
        self.cols = cols
        self.rows = rows
        self.backlight = LCD_BACKLIGHT
        self.bus = None
        self.available = False
        self.status = 'Not initialized'

    def begin(self):
        """Initialize the LCD display if it is present on the I2C bus."""
        try:
            self.bus = smbus2.SMBus(I2C_BUS)
        except FileNotFoundError:
            self.bus = None
            self.available = False
            self.status = f"Missing - /dev/i2c-{I2C_BUS} not found. Enable I2C if you plan to use it"
            print(f" LCD: {self.status}")
            return False
        except Exception as exc:
            self.bus = None
            self.available = False
            self.status = f"Unavailable - could not open I2C bus {I2C_BUS}: {exc}"
            print(f" LCD: {self.status}")
            return False

        time.sleep(0.05)

        try:
            self._write4bits(0x03 << 4)
            time.sleep(0.005)
            self._write4bits(0x03 << 4)
            time.sleep(0.005)
            self._write4bits(0x03 << 4)
            time.sleep(0.001)
            self._write4bits(0x02 << 4)

            self._command(LCD_FUNCTIONSET | LCD_4BITMODE | LCD_2LINE | LCD_5x8DOTS)
            self._command(LCD_DISPLAYCONTROL | LCD_DISPLAYON | LCD_CURSOROFF | LCD_BLINKOFF)
            self.clear()
            self._command(LCD_ENTRYMODESET | LCD_ENTRYLEFT)
            time.sleep(0.001)

            self.available = True
            self.status = f"OK - LCD responded at I2C address 0x{self.address:02X} on bus {I2C_BUS}"
        except Exception as exc:
            self.available = False
            self.status = (
                f"Missing or not responding - no usable LCD at 0x{self.address:02X} on I2C bus {I2C_BUS}: {exc}"
            )
            try:
                self.bus.close()
            except Exception:
                pass
            self.bus = None

        print(f" LCD: {self.status}")
        return self.available

    def _io_error(self, exc):
        """Mark display unavailable on I2C failure so the main loop isn't affected."""
        self.available = False
        print(f"[LCD] I2C error, disabling display: {exc}")
        try:
            self.bus.close()
        except Exception:
            pass
        self.bus = None

    def clear(self):
        if not self.available:
            return
        try:
            self._command(LCD_CLEARDISPLAY)
            time.sleep(0.002)
        except Exception as exc:
            self._io_error(exc)

    def set_cursor(self, col, row):
        if not self.available:
            return
        try:
            row_offsets = [0x00, 0x40, 0x14, 0x54]
            if row >= self.rows:
                row = self.rows - 1
            self._command(LCD_SETDDRAMADDR | (col + row_offsets[row]))
        except Exception as exc:
            self._io_error(exc)

    def print(self, text):
        if not self.available:
            return
        try:
            for char in str(text):
                self._write(ord(char))
        except Exception as exc:
            self._io_error(exc)

    def set_backlight(self, state):
        if not self.available:
            return
        try:
            self.backlight = LCD_BACKLIGHT if state else LCD_NOBACKLIGHT
            self._expander_write(0)
        except Exception as exc:
            self._io_error(exc)

    def get_init_report(self):
        return self.status

    def _command(self, cmd):
        self._send(cmd, 0)

    def _write(self, value):
        self._send(value, RS)

    def _send(self, data, mode):
        high = data & 0xF0
        low = (data << 4) & 0xF0
        self._write4bits(high | mode)
        self._write4bits(low | mode)

    def _write4bits(self, data):
        self._expander_write(data)
        self._pulse_enable(data)

    def _expander_write(self, data):
        if self.bus is None:
            raise RuntimeError('I2C bus is not open')
        self.bus.write_byte(self.address, data | self.backlight)

    def _pulse_enable(self, data):
        self._expander_write(data | EN)
        time.sleep(0.000001)
        self._expander_write(data & ~EN)
        time.sleep(0.00005)

    def cleanup(self):
        if self.bus:
            try:
                self.bus.close()
            except Exception:
                pass
