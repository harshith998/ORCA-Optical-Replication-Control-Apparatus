# Raspberry Pi Chamber Configuration

# ---------- GPIO Pin Definitions ----------
# BCM numbering, updated to match the provided schematic.
SWITCH1_PIN = 14      # EN_S1 (note: conflicts with UART TX if serial is enabled)
SWITCH2_PIN = 4       # EN_S2
SWITCH3_PIN = 17      # EN_S3
PWM_PIN = 12          # PWM output / LED PWM driver

LED_YLW_PIN = 27
LED_GRN_PIN = 23
RJ45_SNS_PIN = 18
ROTARY_A_PIN = 22     # KNOB_A
ROTARY_B_PIN = 24     # KNOB_B
UART_RX_PIN = 15      # RS_RX

# Generic GPIO breakout pins from schematic
GPIO21_PIN = 5
GPIO20_PIN = 6
GPIO18_PIN = 13
GPIO19_PIN = 19
GPIO26_PIN = 26

# ---------- I2C Settings ----------
# Generic I2C bus for optional external devices such as an LCD backpack.
I2C_BUS = 1
I2C_SDA_PIN = 2
I2C_SCL_PIN = 3
LCD_I2C_ADDRESS = 0x27
LCD_COLS = 16
LCD_ROWS = 2

# ---------- SPI Settings ----------
# SPI bus exists on the Pi even if no external device is attached.
SPI_PORT = 0
SPI_DEVICE = 0
POT_CHANNEL = 0       # Legacy ADC channel; ignored if no ADC is attached.
LORA_NRESET_PIN = 8
LORA_CS_PIN = 7
LORA_BUSY_PIN = 20
LORA_DIO1_PIN = 21

# ---------- LoRa RF Configuration (must match satellite firmware) ----------
LORA_SPI_DEVICE  = 1       # spidev0.1 — CE1 (GPIO 7 = LORA_CS_PIN)
LORA_FREQ_MHZ    = 915.0
LORA_BW_KHZ      = 250.0
LORA_SF          = 9
LORA_CR          = 7       # RadioLib notation: 7 → CR4/7
LORA_SYNC_WORD   = 0x12

# ---------- PWM Settings ----------
PWM_FREQ = 500        # 500 Hz PWM (software PWM reliable range on Linux)
MAX_PWM_VALUE = 1023  # 10-bit equivalent (0-1023)

# ---------- Timing Settings ----------
LOOP_DELAY_MS = 100   # 100 milliseconds loop delay

# ---------- Lux Scaling ----------
SCALE_CONSTANT = 2750 # Lux scaling constant

# ---------- Bounds Buffer Settings ----------
LUX_BUFFER_SIZE = 600 # 1 minute of samples at 100ms intervals
