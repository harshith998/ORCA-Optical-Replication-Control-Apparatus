import struct
import time
import spidev
import RPi.GPIO as GPIO

# ---------------------------------------------------------------------------
# SX1262 opcodes
# ---------------------------------------------------------------------------
_CMD_SET_STANDBY        = 0x80
_CMD_SET_RX             = 0x82
_CMD_SET_RF_FREQUENCY   = 0x86
_CMD_SET_PACKET_TYPE    = 0x8A
_CMD_SET_MODULATION     = 0x8B
_CMD_SET_PACKET_PARAMS  = 0x8C
_CMD_SET_BUFFER_BASE    = 0x8F
_CMD_SET_DIO_IRQ        = 0x08
_CMD_GET_IRQ_STATUS     = 0x12
_CMD_CLEAR_IRQ          = 0x02
_CMD_GET_RX_BUF_STATUS  = 0x13
_CMD_READ_BUFFER        = 0x1E
_CMD_WRITE_REGISTER     = 0x0D

# IRQ bit masks
_IRQ_RX_DONE = 0x0002
_IRQ_CRC_ERR = 0x0040

# SX1262 LoRa sync word registers
_REG_SYNC_WORD_MSB = 0x0740
_REG_SYNC_WORD_LSB = 0x0741

# BW register values (SX1262 datasheet Table 13-47)
_BW_REG = {125: 0x04, 250: 0x05, 500: 0x06}

# ---------------------------------------------------------------------------
# Packet decoder
# ---------------------------------------------------------------------------
# Binary layout (51 bytes, little-endian) — matches satellite firmware:
#   uint32  sample_count
#   uint16  f1 f2 fz f3 f4 f5 fy f6 fxl f7 f8 nir clear  (13 channels × 2 B)
#   uint8   gps_valid
#   double  latitude_deg
#   double  longitude_deg
#   uint32  unix_time
_PACKET_STRUCT = struct.Struct('<I 13H B d d I')
PACKET_SIZE    = _PACKET_STRUCT.size  # 51 bytes

CHANNEL_NAMES = ('f1', 'f2', 'fz', 'f3', 'f4', 'f5', 'fy',
                 'f6', 'fxl', 'f7', 'f8', 'nir', 'clear')


def decode_packet(data: bytes) -> dict:
    """
    Decode a 51-byte LoRa payload from the satellite firmware.
    Returns a dict with 'sample_count', 'channels', and 'gps' keys,
    or None if the data length or content is invalid.
    """
    if len(data) != PACKET_SIZE:
        return None
    try:
        fields = _PACKET_STRUCT.unpack(data)
    except struct.error:
        return None

    return {
        'sample_count': fields[0],
        'channels': {name: fields[1 + i] for i, name in enumerate(CHANNEL_NAMES)},
        'gps': {
            'valid':     bool(fields[14]),
            'latitude':  fields[15],
            'longitude': fields[16],
            'unix_time': fields[17],
        },
    }


# ---------------------------------------------------------------------------
# SX1262 receive driver
# ---------------------------------------------------------------------------
class LoRaReceiver:
    """
    Minimal SX1262 receive-only driver using spidev + RPi.GPIO.
    Uses hardware CE (spidev manages CS automatically via the spi_device index).
    GPIO.setmode() must be called before begin().
    """

    def __init__(self, spi_port: int, spi_device: int,
                 reset_pin: int, busy_pin: int, dio1_pin: int):
        self._spi_port   = spi_port
        self._spi_device = spi_device
        self._reset      = reset_pin
        self._busy       = busy_pin
        self._dio1       = dio1_pin
        self._spi        = None

    def begin(self, freq_mhz: float, bw_khz: float,
              sf: int, cr: int, sync_word: int):
        """
        Initialise hardware and start continuous receive mode.
        cr is RadioLib-style (5–8, meaning CR4/5–CR4/8).
        """
        GPIO.setup(self._reset, GPIO.OUT, initial=GPIO.HIGH)
        GPIO.setup(self._busy,  GPIO.IN)
        GPIO.setup(self._dio1,  GPIO.IN)

        self._spi = spidev.SpiDev()
        self._spi.open(self._spi_port, self._spi_device)
        self._spi.max_speed_hz = 1_000_000
        self._spi.mode = 0

        # Hardware reset
        GPIO.output(self._reset, GPIO.LOW)
        time.sleep(0.002)
        GPIO.output(self._reset, GPIO.HIGH)
        time.sleep(0.010)
        self._wait_busy()

        self._cmd(_CMD_SET_STANDBY,    [0x00])          # RC oscillator standby
        self._cmd(_CMD_SET_PACKET_TYPE, [0x01])          # LoRa mode

        # RF frequency: fword = freq_hz * 2^25 / 32 MHz
        fword = round(freq_mhz * 1e6 * (1 << 25) / 32e6)
        self._cmd(_CMD_SET_RF_FREQUENCY, [
            (fword >> 24) & 0xFF,
            (fword >> 16) & 0xFF,
            (fword >>  8) & 0xFF,
             fword        & 0xFF,
        ])

        # Modulation params: SF, BW, CR, LDRO=0
        bw_reg = _BW_REG.get(int(bw_khz), 0x05)
        cr_reg = cr - 4  # CR4/5→1, CR4/6→2, CR4/7→3, CR4/8→4
        self._cmd(_CMD_SET_MODULATION, [sf, bw_reg, cr_reg, 0x00])

        # Packet params: preamble=8, variable header, max payload=255, CRC on, IQ normal
        self._cmd(_CMD_SET_PACKET_PARAMS, [0x00, 0x08, 0x00, 0xFF, 0x01, 0x00])

        # Sync word (SX1262 stores it across two nibble-encoded registers)
        sw_msb = (sync_word & 0xF0) | 0x04
        sw_lsb = ((sync_word & 0x0F) << 4) | 0x04
        self._write_reg(_REG_SYNC_WORD_MSB, [sw_msb, sw_lsb])

        # Route RxDone + CrcErr to DIO1
        irq = _IRQ_RX_DONE | _IRQ_CRC_ERR
        self._cmd(_CMD_SET_DIO_IRQ, [
            (irq >> 8) & 0xFF, irq & 0xFF,  # global mask
            (irq >> 8) & 0xFF, irq & 0xFF,  # DIO1 mask
            0x00, 0x00,                      # DIO2 (unused)
            0x00, 0x00,                      # DIO3 (unused)
        ])

        self._cmd(_CMD_SET_BUFFER_BASE, [0x00, 0x00])
        self._cmd(_CMD_SET_RX, [0xFF, 0xFF, 0xFF])      # continuous RX

    def poll(self) -> bytes:
        """
        Non-blocking packet check. Returns raw payload bytes if a valid packet
        has arrived since the last call, otherwise None.
        """
        if not GPIO.input(self._dio1):
            return None

        irq = self._get_irq()
        self._clear_irq(irq)

        if irq & _IRQ_CRC_ERR:
            return None
        if not (irq & _IRQ_RX_DONE):
            return None

        # Payload length and buffer start pointer
        resp        = self._cmd(_CMD_GET_RX_BUF_STATUS, [0x00, 0x00])
        payload_len = resp[1]
        buf_offset  = resp[2]

        if payload_len == 0:
            return None

        # ReadBuffer: [cmd, offset, status_nop, data×N]
        raw = self._cmd(_CMD_READ_BUFFER, [buf_offset] + [0x00] * (payload_len + 1))
        return bytes(raw[2: 2 + payload_len])

    def close(self):
        if self._spi:
            try:
                self._spi.close()
            except Exception:
                pass

    # --- Internal SPI helpers ---

    def _wait_busy(self, timeout_s: float = 1.0):
        deadline = time.time() + timeout_s
        while GPIO.input(self._busy):
            if time.time() > deadline:
                raise TimeoutError("SX1262 BUSY pin did not clear within timeout")
            time.sleep(0.001)

    def _cmd(self, opcode: int, params: list = None) -> list:
        self._wait_busy()
        return self._spi.xfer2([opcode] + (params or []))

    def _write_reg(self, addr: int, data: list):
        self._wait_busy()
        self._spi.xfer2([_CMD_WRITE_REGISTER, (addr >> 8) & 0xFF, addr & 0xFF] + data)

    def _get_irq(self) -> int:
        resp = self._cmd(_CMD_GET_IRQ_STATUS, [0x00, 0x00])
        return (resp[1] << 8) | resp[2]

    def _clear_irq(self, mask: int):
        self._cmd(_CMD_CLEAR_IRQ, [(mask >> 8) & 0xFF, mask & 0xFF])
