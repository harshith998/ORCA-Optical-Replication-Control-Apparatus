import struct
from LoRaRF import SX126x

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
# SX1262 receive driver (LoRaRF library)
# ---------------------------------------------------------------------------
class LoRaReceiver:
    """
    SX1262 receive-only driver using the LoRaRF SX126x library.
    Requires a TCXO-equipped module (DIO3 as TCXO control).
    GPIO.setmode() is NOT required — LoRaRF handles GPIO internally.
    """

    def __init__(self, spi_port: int, spi_device: int,
                 reset_pin: int, busy_pin: int, dio1_pin: int):
        self._spi_port   = spi_port
        self._spi_device = spi_device
        self._reset      = reset_pin
        self._busy       = busy_pin
        # dio1_pin unused — polling mode (irq=-1) avoids edge-detection issues
        self._lora = SX126x()

    def begin(self, freq_mhz: float, bw_khz: float,
              sf: int, cr: int, sync_word: int):
        """
        Initialise hardware and start continuous receive mode.
        cr is RadioLib-style (5–8, meaning CR4/5–CR4/8).
        sync_word is the 1-byte satellite value (e.g. 0x12).
        """
        if not self._lora.begin(self._spi_port, self._spi_device,
                                self._reset, self._busy, -1):
            raise RuntimeError("SX126x begin() failed — check SPI and GPIO wiring")

        # TCXO on DIO3 — required for this module to lock on to any frequency
        self._lora.setDio3TcxoCtrl(self._lora.DIO3_OUTPUT_1_8, self._lora.TCXO_DELAY_10)

        self._lora.setFrequency(int(freq_mhz * 1e6))
        self._lora.setRxGain(self._lora.RX_GAIN_POWER_SAVING)
        self._lora.setLoRaModulation(sf, int(bw_khz * 1000), cr)
        self._lora.setLoRaPacket(self._lora.HEADER_EXPLICIT, 12, 255, True)

        # LoRaRF setSyncWord expects the 2-byte register encoding.
        # Satellite sync word 0x12 → register encoding 0x1424.
        sw_msb = (sync_word & 0xF0) | 0x04
        sw_lsb = ((sync_word & 0x0F) << 4) | 0x04
        self._lora.setSyncWord((sw_msb << 8) | sw_lsb)

        self._lora.request(self._lora.RX_CONTINUOUS)

    def poll(self) -> bytes:
        """
        Non-blocking packet check. Returns raw payload bytes if a packet
        has arrived since the last call, otherwise None.
        """
        length = self._lora.available()
        if not length:
            return None

        payload = bytes(self._lora.read() for _ in range(length))
        self._lora.request(self._lora.RX_CONTINUOUS)
        return payload

    def close(self):
        pass
