# Raspberry Pi Chamber Configuration
# All GPIO values use BCM numbering.

# ---------- Header / board wiring from schematic ----------
I2C_SDA_PIN = 2
I2C_SCL_PIN = 3

EN_S2_PIN = 4
GENERIC_GPIO21_PIN = 5   # Header pin 29, net label GPIO21
GENERIC_GPIO20_PIN = 6   # Header pin 31, net label GPIO20

UART_TX_PIN = 14         # Header pin 8, shared with EN_S1 on schematic
UART_RX_PIN = 15         # Header pin 10, net label RS_RX
GENERIC_GPIO17_PIN = 16  # Header pin 36, net label GPIO17
EN_S3_PIN = 17
RJ45_SNS_PIN = 18
GENERIC_GPIO19_PIN = 19  # Header pin 35, net label GPIO19
GENERIC_GPIO26_PIN = 26  # Header pin 37, net label GPIO26
LED_YLW_PIN = 27

SPI_MOSI_PIN = 10
SPI_MISO_PIN = 9
SPI_SCLK_PIN = 11
SPI_CE0_PIN = 8          # Header pin 24, net label NRESET
SPI_CE1_PIN = 7          # Header pin 26, net label CS_1

PWM_PIN = 12             # Header pin 32, dedicated PWM output
GENERIC_GPIO18_PIN = 13  # Header pin 33, net label GPIO18
LED_GRN_PIN = 23
KNOB_A_PIN = 22
KNOB_B_PIN = 24

LORA_NRESET_PIN = 8      # BCM8 / CE0, board net label NRESET
LORA_CS_PIN = 7          # BCM7 / CE1, board net label CS_1
LORA_BUSY_PIN = 20       # BCM20 / header pin 38, board net label BUSY
LORA_DIO1_PIN = 21       # BCM21 / header pin 40, board net label DIO1

# ---------- Compatibility aliases used by the current code ----------
# Current application code still expects two digital mode/enable inputs.
SWITCH1_PIN = 14         # EN_S1 on schematic (conflicts with UART_TX_PIN / serial0)
SWITCH2_PIN = EN_S2_PIN  # BCM4
SWITCH3_PIN = EN_S3_PIN  # BCM17, available for future use

# Rotary encoder wiring (the current code does NOT read an encoder yet).
ROTARY_A_PIN = KNOB_A_PIN
ROTARY_B_PIN = KNOB_B_PIN

# ---------- I2C Settings ----------
# I2C bus is generic and available for external devices.
LCD_I2C_ADDRESS = 0x27
LCD_COLS = 16
LCD_ROWS = 2

# ---------- SPI Settings ----------
# SPI is wired to the LoRa module, not an MCP3008 ADC.
SPI_PORT = 0
SPI_DEVICE = 0
POT_CHANNEL = 0  # Legacy placeholder only; current code still expects an ADC channel.

# ---------- UART Settings ----------
# RS_RX comes in on BCM15 (/dev/serial0 RX). Note that BCM14 is also wired as EN_S1,
# which conflicts with serial0 TX if UART is enabled.
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
