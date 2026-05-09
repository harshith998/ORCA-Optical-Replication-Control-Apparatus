# Raspberry Pi Chamber Configuration

# ---------- GPIO Pin Definitions ----------
# BCM numbering, updated to match the provided schematic.

# 12V switch pins 
SWITCH1_PIN = 14      # EN_S1
SWITCH2_PIN = 4       # EN_S2
SWITCH3_PIN = 17      # EN_S3

# 24V LED PWM pin (Do Not Change)
PWM_PIN = 12

# RJ45 pins
LED_YLW_PIN = 27
LED_GRN_PIN = 23
RJ45_SNS_PIN = 18

# Rotary knob pins
ROTARY_A_PIN = 22     # KNOB_A
ROTARY_B_PIN = 24     # KNOB_B
ROTARY_BTN_PIN = 5    # KNOB button click

# Additional generic GPIO breakout pins from schematic
GPIO21_PIN = 5
GPIO20_PIN = 6
GPIO18_PIN = 13
GPIO19_PIN = 19
GPIO26_PIN = 26

# ---------- I2C Settings ----------
I2C_BUS = 1
I2C_SDA_PIN = 2
I2C_SCL_PIN = 3

# LCD configuration
LCD_I2C_ADDRESS = 0x27
LCD_COLS = 20
LCD_ROWS = 4

# LoRa module GPIO cofiguration
LORA_NRESET_PIN = 8
LORA_CS_PIN = 7
LORA_BUSY_PIN = 20
LORA_DIO1_PIN = 21

# ---------- LoRa RF Configuration (must match satellite firmware) ----------
LORA_SPI_PORT    = 0       # SPI bus 0
LORA_SPI_DEVICE  = 1       # spidev0.1 — CE1 (GPIO 7 = LORA_CS_PIN)
LORA_FREQ_MHZ    = 915.0
LORA_BW_KHZ      = 250.0
LORA_SF          = 9
LORA_CR          = 7       # RadioLib notation: 7 → CR4/7
LORA_SYNC_WORD   = 0x12

# ---------- PWM Settings ----------
PWM_FREQ = 1000       # 1000 Hz
MAX_PWM_VALUE = 1023  # 10-bit equivalent (0-1023)
KNOB_STEP = 10        # PWM units per rotary encoder detent in manual mode

# ---------- Timing Settings ----------
LOOP_DELAY_MS = 100   # 100 milliseconds loop delay

# ---------- Hotspot Settings ----------
HOTSPOT_IP   = '10.42.0.1'
HOTSPOT_SSID = 'ORCA-Pi'
WEB_PORT     = 5000

# ---------- RS-485 / Wired UART Settings ----------
RS_UART_DEVICE = '/dev/serial0'  # Primary hardware UART RX
RS_RX_BAUD     = 115200

# TODO: Analyze this code

# ---------- Lux Scaling ----------
SCALE_CONSTANT = 2750 # Lux scaling constant

# ---------- Bounds Buffer Settings ----------
LUX_BUFFER_SIZE = 600 # 1 minute of samples at 100ms intervals
