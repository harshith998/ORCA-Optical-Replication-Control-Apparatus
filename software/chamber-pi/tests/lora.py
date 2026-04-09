"""
Standalone SX1262 receive test — no LoRaRF dependency.
Directly drives the chip via spidev + RPi.GPIO, same approach as lora_receiver.py.
Prints RSSI/SNR for every packet received.
"""
import struct
import time
import spidev
import RPi.GPIO as GPIO

# ---------------------------------------------------------------------------
# Pin assignments (BCM) — must match config.py / schematic
# ---------------------------------------------------------------------------
RESET_PIN = 8
BUSY_PIN  = 20
DIO1_PIN  = 21
SPI_PORT  = 0
SPI_DEV   = 1   # CE1

# ---------------------------------------------------------------------------
# SX1262 opcodes
# ---------------------------------------------------------------------------
CMD_SET_STANDBY           = 0x80
CMD_SET_PACKET_TYPE       = 0x8A
CMD_SET_RF_FREQUENCY      = 0x86
CMD_SET_MODULATION        = 0x8B
CMD_SET_PACKET_PARAMS     = 0x8C
CMD_SET_BUFFER_BASE       = 0x8F
CMD_SET_DIO_IRQ           = 0x08
CMD_SET_DIO2_RF_SWITCH    = 0x9D   # tell chip DIO2 drives the RF switch
CMD_SET_RX                = 0x82
CMD_GET_IRQ_STATUS        = 0x12
CMD_CLEAR_IRQ             = 0x02
CMD_GET_RX_BUF_STATUS     = 0x13
CMD_READ_BUFFER           = 0x1E
CMD_WRITE_REGISTER        = 0x0D
CMD_GET_PACKET_STATUS     = 0x14
CMD_GET_STATUS            = 0xC0
CMD_READ_REGISTER         = 0x1D

CHIP_MODES = {2: 'STDBY_RC', 3: 'STDBY_XOSC', 4: 'TX', 5: 'RX', 6: 'CAD'}

IRQ_RX_DONE = 0x0002
IRQ_CRC_ERR = 0x0040

REG_SYNC_MSB = 0x0740

# ---------------------------------------------------------------------------
# SPI helpers
# ---------------------------------------------------------------------------
spi = spidev.SpiDev()

def wait_busy(timeout=1.0):
    deadline = time.time() + timeout
    while GPIO.input(BUSY_PIN):
        if time.time() > deadline:
            raise TimeoutError("SX1262 BUSY stuck HIGH")
        time.sleep(0.001)

def cmd(opcode, params=None):
    wait_busy()
    r = spi.xfer2([opcode] + (params or []))
    wait_busy()   # wait for chip to finish processing the command
    return r

def write_reg(addr, data):
    wait_busy()
    spi.xfer2([CMD_WRITE_REGISTER, (addr >> 8) & 0xFF, addr & 0xFF] + data)
    wait_busy()

def chip_mode():
    wait_busy()
    r = spi.xfer2([CMD_GET_STATUS, 0x00])
    wait_busy()
    return (r[1] >> 4) & 0x07

def get_irq():
    r = cmd(CMD_GET_IRQ_STATUS, [0x00, 0x00])
    return (r[1] << 8) | r[2]

def clear_irq(mask):
    cmd(CMD_CLEAR_IRQ, [(mask >> 8) & 0xFF, mask & 0xFF])

def read_reg(addr):
    """Read one byte from a chip register. Returns the byte value."""
    wait_busy()
    r = spi.xfer2([CMD_READ_REGISTER, (addr >> 8) & 0xFF, addr & 0xFF, 0x00, 0x00])
    wait_busy()
    return r[4]

def get_packet_status():
    r = cmd(CMD_GET_PACKET_STATUS, [0x00, 0x00, 0x00])
    rssi = -r[1] / 2.0
    snr  = struct.unpack('b', bytes([r[2]]))[0] / 4.0
    return rssi, snr

def enter_rx():
    cmd(CMD_SET_RX, [0xFF, 0xFF, 0xFF])   # continuous RX

# ---------------------------------------------------------------------------
# Hardware init
# ---------------------------------------------------------------------------
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
GPIO.setup(RESET_PIN, GPIO.OUT, initial=GPIO.HIGH)
GPIO.setup(BUSY_PIN,  GPIO.IN)
GPIO.setup(DIO1_PIN,  GPIO.IN)

spi.open(SPI_PORT, SPI_DEV)
spi.max_speed_hz = 1_000_000
spi.mode = 0

# Hardware reset
GPIO.output(RESET_PIN, GPIO.LOW)
time.sleep(0.002)
GPIO.output(RESET_PIN, GPIO.HIGH)
time.sleep(0.010)
wait_busy()

# ---------------------------------------------------------------------------
# Radio config — must match satellite: 915 MHz, BW250, SF9, CR4/7, sync 0x12
# ---------------------------------------------------------------------------
cmd(CMD_SET_STANDBY,     [0x00])   # STDBY_RC
cmd(CMD_SET_PACKET_TYPE, [0x01])   # LoRa mode

# Tell the chip that DIO2 controls the RF switch (needed on most SX1262 modules)
cmd(CMD_SET_DIO2_RF_SWITCH, [0x01])

fword = round(915e6 * (1 << 25) / 32e6)
cmd(CMD_SET_RF_FREQUENCY, [
    (fword >> 24) & 0xFF,
    (fword >> 16) & 0xFF,
    (fword >>  8) & 0xFF,
     fword        & 0xFF,
])

# SF=9, BW=250kHz (0x05), CR4/7 → cr_reg=3, LDRO=0
cmd(CMD_SET_MODULATION, [9, 0x05, 3, 0x00])

# Preamble=8, explicit header, max payload=255, CRC on, IQ normal
cmd(CMD_SET_PACKET_PARAMS, [0x00, 0x08, 0x00, 0xFF, 0x01, 0x00])

# Sync word 0x12 → MSB reg = (0x12 & 0xF0)|0x04 = 0x14
#                   LSB reg = ((0x12 & 0x0F)<<4)|0x04 = 0x24
write_reg(REG_SYNC_MSB, [0x14, 0x24])

# Route RxDone + CrcErr to DIO1
irq_mask = IRQ_RX_DONE | IRQ_CRC_ERR
cmd(CMD_SET_DIO_IRQ, [
    (irq_mask >> 8) & 0xFF, irq_mask & 0xFF,   # global mask
    (irq_mask >> 8) & 0xFF, irq_mask & 0xFF,   # DIO1 mask
    0x00, 0x00,                                 # DIO2
    0x00, 0x00,                                 # DIO3
])

cmd(CMD_SET_BUFFER_BASE, [0x00, 0x00])

# ---------------------------------------------------------------------------
# SPI sanity check: read back the sync word we just wrote
# Default power-on value is 0x34 (public LoRa); we wrote 0x14.
# If we read 0x14 back → SPI writes are working.
# If we read 0x34 → writes are not reaching the chip (wrong CE / broken SPI).
# If we read 0x00 or 0xFF → MISO is floating, SPI is not connected at all.
# ---------------------------------------------------------------------------
sync_readback = read_reg(REG_SYNC_MSB)
print(f"SPI check — sync word MSB readback: 0x{sync_readback:02X}  "
      f"(wrote 0x14, power-on default 0x34)")
if sync_readback == 0x14:
    print("  -> SPI OK: chip is receiving and executing commands")
elif sync_readback == 0x34:
    print("  -> SPI PARTIAL: chip responds but writes not landing — wrong CE pin?")
else:
    print(f"  -> SPI FAIL: unexpected value — MISO floating or wrong device on bus")

enter_rx()

# Confirm chip actually entered RX before starting the loop
mode = chip_mode()
mode_str = CHIP_MODES.get(mode, f'unknown({mode})')
print(f"Init complete — chip mode after SetRx: {mode_str}")
if mode != 5:
    print("WARNING: chip is NOT in RX mode — check SPI wiring / CE pin")

print(f"\nListening — 915 MHz  BW250  SF9  CR4/7  sync=0x12")
print(f"{'PKT':>4}  {'LEN':>4}  {'RSSI':>10}  {'SNR':>8}")

pkt_count = 0
last_heartbeat = time.time()
HEARTBEAT_INTERVAL = 5.0

try:
    while True:
        now = time.time()
        if now - last_heartbeat >= HEARTBEAT_INTERVAL:
            mode     = chip_mode()
            mode_str = CHIP_MODES.get(mode, f'unknown({mode})')
            print(f"  [heartbeat] chip mode={mode_str}  pkts so far={pkt_count}")
            last_heartbeat = now

        if GPIO.input(DIO1_PIN):
            irq_flags = get_irq()
            rssi, snr = get_packet_status()
            clear_irq(irq_flags)

            if irq_flags & IRQ_CRC_ERR:
                print(f"{'CRC':>4}  {'---':>4}  {rssi:>8.2f} dBm  {snr:>6.2f} dB")
            elif irq_flags & IRQ_RX_DONE:
                r       = cmd(CMD_GET_RX_BUF_STATUS, [0x00, 0x00])
                pkt_len = r[1]
                pkt_count += 1
                print(f"{pkt_count:>4}  {pkt_len:>4}  {rssi:>8.2f} dBm  {snr:>6.2f} dB")
            else:
                print(f"DIO1 spurious  IRQ=0x{irq_flags:04X}")

            enter_rx()

        time.sleep(0.005)

except KeyboardInterrupt:
    print(f"\nDone. {pkt_count} packets received.")
finally:
    spi.close()
    GPIO.cleanup()
