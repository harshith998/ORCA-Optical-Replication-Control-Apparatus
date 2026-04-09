import struct
import time
import spidev
import RPi.GPIO as GPIO

# ---------------------------------------------------------------------------
# SX1262 opcodes
# ---------------------------------------------------------------------------
_CMD_SET_STANDBY       = 0x80
_CMD_SET_PACKET_TYPE   = 0x8A
_CMD_SET_RF_FREQUENCY  = 0x86
_CMD_SET_MODULATION    = 0x8B
_CMD_SET_PACKET_PARAMS = 0x8C
_CMD_SET_BUFFER_BASE   = 0x8F
_CMD_SET_DIO_IRQ       = 0x08
_CMD_SET_DIO2_RF_SW    = 0x9D
_CMD_SET_DIO3_TCXO     = 0x97
_CMD_SET_RX            = 0x82
_CMD_GET_IRQ_STATUS    = 0x12
_CMD_CLEAR_IRQ         = 0x02
_CMD_GET_RX_BUF_STATUS = 0x13
_CMD_READ_BUFFER       = 0x1E
_CMD_WRITE_REGISTER    = 0x0D

_CMD_GET_PACKET_STATUS = 0x14
_CMD_GET_STATUS        = 0xC0

_IRQ_RX_DONE = 0x0002
_IRQ_CRC_ERR = 0x0040

_REG_SYNC_MSB = 0x0740

_CHIP_MODES = {2: 'STDBY_RC', 3: 'STDBY_XOSC', 4: 'TX', 5: 'RX', 6: 'CAD'}

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
# SX1262 receive driver — direct spidev, matches working test implementation
# ---------------------------------------------------------------------------
class LoRaReceiver:
    """
    Minimal SX1262 receive-only driver using spidev + RPi.GPIO.
    GPIO.setmode(GPIO.BCM) must be called before begin() (io_controller does this).
    Mirrors the direct spidev test script exactly.
    """

    def __init__(self, spi_port: int, spi_device: int,
                 reset_pin: int, busy_pin: int, dio1_pin: int):
        self._spi_port   = spi_port
        self._spi_device = spi_device
        self._reset      = reset_pin
        self._busy       = busy_pin
        self._dio1       = dio1_pin
        self._spi        = None
        self._irq_mask   = _IRQ_RX_DONE | _IRQ_CRC_ERR
        self._pkt_count  = 0
        self._last_beat  = 0.0

    # --- Public API ---

    def begin(self, freq_mhz: float, bw_khz: float,
              sf: int, cr: int, sync_word: int):
        """
        Initialise hardware and enter continuous RX mode.
        cr is RadioLib-style (5–8 → CR4/5–CR4/8); internally converted to SX1262 register value.
        sync_word is the raw 1-byte value (e.g. 0x12); encoded to 2-byte register format internally.
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

        self._cmd(_CMD_SET_STANDBY,     [0x00])   # STDBY_RC
        self._cmd(_CMD_SET_PACKET_TYPE, [0x01])   # LoRa mode

        # TCXO on DIO3: 1.8 V, 10 ms delay (640 × 15.625 µs = 0x000280)
        self._cmd(_CMD_SET_DIO3_TCXO, [0x02, 0x00, 0x02, 0x80])

        # DIO2 drives the RF switch
        self._cmd(_CMD_SET_DIO2_RF_SW, [0x01])

        # RF frequency
        fword = round(freq_mhz * 1e6 * (1 << 25) / 32e6)
        self._cmd(_CMD_SET_RF_FREQUENCY, [
            (fword >> 24) & 0xFF,
            (fword >> 16) & 0xFF,
            (fword >>  8) & 0xFF,
             fword        & 0xFF,
        ])

        # Modulation: SF, BW reg, CR reg (RadioLib cr 5–8 → reg 1–4), LDRO=0
        bw_reg = {125: 0x04, 250: 0x05, 500: 0x06}.get(int(bw_khz), 0x05)
        cr_reg = cr - 4
        self._cmd(_CMD_SET_MODULATION, [sf, bw_reg, cr_reg, 0x00])

        # Packet: preamble=8, explicit header, max payload=255, CRC on, IQ normal
        self._cmd(_CMD_SET_PACKET_PARAMS, [0x00, 0x08, 0x00, 0xFF, 0x01, 0x00])

        # Sync word: encode 1-byte value to SX1262 2-byte register format
        sw_msb = (sync_word & 0xF0) | 0x04
        sw_lsb = ((sync_word & 0x0F) << 4) | 0x04
        self._write_reg(_REG_SYNC_MSB, [sw_msb, sw_lsb])

        # Route RxDone + CrcErr to DIO1
        irq = self._irq_mask
        self._cmd(_CMD_SET_DIO_IRQ, [
            (irq >> 8) & 0xFF, irq & 0xFF,
            (irq >> 8) & 0xFF, irq & 0xFF,
            0x00, 0x00,
            0x00, 0x00,
        ])

        self._cmd(_CMD_SET_BUFFER_BASE, [0x00, 0x00])
        self._cmd(_CMD_SET_RX, [0xFF, 0xFF, 0xFF])   # continuous RX

        # Confirm chip entered RX
        r    = self._spi.xfer2([_CMD_GET_STATUS, 0x00])
        mode = (r[1] >> 4) & 0x07
        print(f"[LoRa] Init complete — chip mode: {_CHIP_MODES.get(mode, f'unknown({mode})')}")

    def poll(self) -> bytes:
        """
        Non-blocking packet check. Returns raw payload bytes on RxDone,
        empty bytes on CRC error, or None if nothing has arrived.
        """
        now = time.time()
        if now - self._last_beat >= 1.0:
            r        = self._spi.xfer2([_CMD_GET_STATUS, 0x00])
            mode     = (r[1] >> 4) & 0x07
            mode_str = _CHIP_MODES.get(mode, f'unknown({mode})')
            print(f"[LoRa] {now:.1f}  mode={mode_str:<12}  pkts={self._pkt_count}")
            self._last_beat = now

        if not GPIO.input(self._dio1):
            return None

        # Response: [status(during opcode), NOP, IRQ[15:8], IRQ[7:0]]
        r         = self._cmd(_CMD_GET_IRQ_STATUS, [0x00, 0x00, 0x00])
        irq_flags = (r[2] << 8) | r[3]
        self._cmd(_CMD_CLEAR_IRQ, [(self._irq_mask >> 8) & 0xFF, self._irq_mask & 0xFF])

        # Get RSSI/SNR before clearing IRQ
        # Response: [status(during opcode), NOP, RssiPkt, SnrPkt, SignalRssiPkt]
        ps   = self._cmd(_CMD_GET_PACKET_STATUS, [0x00, 0x00, 0x00, 0x00])
        rssi = -ps[2] / 2.0
        snr  = struct.unpack('b', bytes([ps[3]]))[0] / 4.0

        if irq_flags & _IRQ_CRC_ERR:
            print(f"[LoRa] CRC ERR  RSSI={rssi:.1f} dBm  SNR={snr:.1f} dB")
            self._cmd(_CMD_SET_RX, [0xFF, 0xFF, 0xFF])
            return b''

        if not (irq_flags & _IRQ_RX_DONE):
            self._cmd(_CMD_SET_RX, [0xFF, 0xFF, 0xFF])
            return None

        # Response: [status(during opcode), NOP, PayloadLen, BufOffset]
        r          = self._cmd(_CMD_GET_RX_BUF_STATUS, [0x00, 0x00, 0x00])
        pkt_len    = r[2]
        buf_offset = r[3]

        if pkt_len == 0:
            self._cmd(_CMD_SET_RX, [0xFF, 0xFF, 0xFF])
            return None

        # ReadBuffer: [cmd, offset, NOP(status), data × pkt_len]
        raw     = self._cmd(_CMD_READ_BUFFER, [buf_offset] + [0x00] * (pkt_len + 1))
        payload = bytes(raw[3: 3 + pkt_len])

        self._pkt_count += 1
        print(f"[LoRa] RX DONE  len={pkt_len:3d}  RSSI={rssi:.1f} dBm  SNR={snr:.1f} dB  pkts={self._pkt_count}")

        self._cmd(_CMD_SET_RX, [0xFF, 0xFF, 0xFF])   # re-arm
        return payload

    def close(self):
        if self._spi:
            try:
                self._spi.close()
            except Exception:
                pass

    # --- Internal helpers ---

    def _wait_busy(self, timeout_s: float = 2.0):
        deadline = time.time() + timeout_s
        while GPIO.input(self._busy):
            if time.time() > deadline:
                raise TimeoutError("SX1262 BUSY pin did not clear within timeout")
            time.sleep(0.001)

    def _cmd(self, opcode: int, params: list = None) -> list:
        self._wait_busy()
        r = self._spi.xfer2([opcode] + (params or []))
        self._wait_busy()
        return r

    def _write_reg(self, addr: int, data: list):
        self._wait_busy()
        self._spi.xfer2([_CMD_WRITE_REGISTER, (addr >> 8) & 0xFF, addr & 0xFF] + data)
        self._wait_busy()
