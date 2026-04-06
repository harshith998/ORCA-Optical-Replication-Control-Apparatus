import smbus2
import time
from config import LCD_I2C_ADDRESS, LCD_COLS, LCD_ROWS

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
EN = 0b00000100  # Enable bit
RW = 0b00000010  # Read/Write bit
RS = 0b00000001  # Register select bit


class LCDDisplay:
    def __init__(self, address=LCD_I2C_ADDRESS, cols=LCD_COLS, rows=LCD_ROWS):
        self.address = address
        self.cols = cols
        self.rows = rows
        self.backlight = LCD_BACKLIGHT
        self.bus = None
        self.available = False

    def begin(self):
        """Initialize the LCD display."""
        try:
            self.bus = smbus2.SMBus(1)  # RPi uses I2C bus 1
            self.available = True
        except FileNotFoundError:
            print("WARNING: I2C bus /dev/i2c-1 not found. LCD disabled.")
            self.bus = None
            self.available = False
            return
        except OSError as e:
            print(f"WARNING: Unable to open LCD I2C bus: {e}. LCD disabled.")
            self.bus = None
            self.available = False
            return

        time.sleep(0.05)

        try:
            # Initialize in 4-bit mode
            self._write4bits(0x03 << 4)
            time.sleep(0.005)
            self._write4bits(0x03 << 4)
            time.sleep(0.005)
            self._write4bits(0x03 << 4)
            time.sleep(0.001)
            self._write4bits(0x02 << 4)

            # Set function: 4-bit, 2 lines, 5x8 dots
            self._command(LCD_FUNCTIONSET | LCD_4BITMODE | LCD_2LINE | LCD_5x8DOTS)
            # Display on, cursor off, blink off
            self._command(LCD_DISPLAYCONTROL | LCD_DISPLAYON | LCD_CURSOROFF | LCD_BLINKOFF)
            # Clear display
            self.clear()
            # Entry mode: left to right
            self._command(LCD_ENTRYMODESET | LCD_ENTRYLEFT)
            time.sleep(0.001)
        except OSError as e:
            print(f"WARNING: LCD initialization failed: {e}. LCD disabled.")
            self.cleanup()
            self.available = False

    def clear(self):
        """Clear the display."""
        if not self.available:
            return
        self._command(LCD_CLEARDISPLAY)
        time.sleep(0.002)

    def set_cursor(self, col, row):
        """Set cursor position."""
        if not self.available:
            return
        row_offsets = [0x00, 0x40, 0x14, 0x54]
        if row >= self.rows:
            row = self.rows - 1
        self._command(LCD_SETDDRAMADDR | (col + row_offsets[row]))

    def print(self, text):
        """Print text at current cursor position."""
        if not self.available:
            return
        for char in str(text):
            self._write(ord(char))

    def set_backlight(self, state):
        """Turn backlight on/off."""
        self.backlight = LCD_BACKLIGHT if state else LCD_NOBACKLIGHT
        if not self.available:
            return
        self._expander_write(0)

    def _command(self, cmd):
        """Send command to LCD."""
        self._send(cmd, 0)

    def _write(self, value):
        """Write data to LCD."""
        self._send(value, RS)

    def _send(self, data, mode):
        """Send byte to LCD (4-bit mode)."""
        high = data & 0xF0
        low = (data << 4) & 0xF0
        self._write4bits(high | mode)
        self._write4bits(low | mode)

    def _write4bits(self, data):
        """Write 4 bits with enable pulse."""
        if not self.available or self.bus is None:
            return
        self._expander_write(data)
        self._pulse_enable(data)

    def _disable_lcd(self, message):
        """Disable the LCD after an I2C communication failure."""
        if self.available:
            print(f"WARNING: {message}. LCD disabled.")
        self.cleanup()

    def _expander_write(self, data):
        """Write to I2C expander."""
        if not self.available or self.bus is None:
            return
        try:
            self.bus.write_byte(self.address, data | self.backlight)
        except OSError as e:
            self._disable_lcd(f"LCD I2C write failed at address 0x{self.address:02X}: {e}")

    def _pulse_enable(self, data):
        """Pulse the enable pin."""
        if not self.available or self.bus is None:
            return
        self._expander_write(data | EN)
        time.sleep(0.000001)
        self._expander_write(data & ~EN)
        time.sleep(0.00005)

    def cleanup(self):
        """Cleanup I2C bus."""
        if self.bus:
            try:
                self.bus.close()
            except Exception:
                pass
        self.bus = None
        self.available = False
