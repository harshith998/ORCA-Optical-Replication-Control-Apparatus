# Raspberry Pi Chamber Configuration

# ---------- GPIO Pin Definitions ----------
# BCM numbering
SWITCH1_PIN = 14      # Input switch 1 (mode: analog/lux)
SWITCH2_PIN = 12      # Input switch 2 (PWM on/off)
PWM_PIN = 18          # PWM output (GPIO18 supports hardware PWM)

# ---------- I2C Settings ----------
LCD_I2C_ADDRESS = 0x27
LCD_COLS = 16
LCD_ROWS = 2

# ---------- SPI Settings (for MCP3008 ADC) ----------
# Pi doesn't have built-in ADC, using MCP3008
SPI_PORT = 0
SPI_DEVICE = 0
POT_CHANNEL = 0       # MCP3008 channel for potentiometer

# ---------- UART Settings ----------
UART_PORT = "/dev/serial0"
UART_BAUD = 115200

# ---------- PWM Settings ----------
PWM_FREQ = 5000       # 5 kHz PWM
MAX_PWM_VALUE = 1023  # 10-bit equivalent (0-1023)

# ---------- Timing Settings ----------
LOOP_DELAY_MS = 100   # 100 milliseconds loop delay

# ---------- Lux Scaling ----------
SCALE_CONSTANT = 2750 # Lux scaling constant

# ---------- Bounds Buffer Settings ----------
LUX_BUFFER_SIZE = 600 # 1 minute of samples at 100ms intervals