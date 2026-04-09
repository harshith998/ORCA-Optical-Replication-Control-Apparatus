import os, sys
currentdir = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.dirname(os.path.dirname(currentdir)))
from LoRaRF import SX126x
import time

LoRa = SX126x()
print("Begin LoRa radio")
if not LoRa.begin(0, 1, 8, 20, -1):
    raise Exception("Something wrong, can't begin LoRa radio")

LoRa.setFrequency(915000000)
LoRa.setRxGain(LoRa.RX_GAIN_BOOSTED)

sf = 9
bw = 250000
cr = 7
LoRa.setLoRaModulation(sf, bw, cr)
LoRa.setLoRaPacket(LoRa.HEADER_EXPLICIT, 12, 255, True)
LoRa.setSyncWord(0x1424)

print("Listening for packets (915 MHz, BW250, SF9, CR7, sync=0x1424)...\n")
LoRa.request(LoRa.RX_CONTINUOUS)

while True:
    if LoRa.available():
        # Drain the buffer
        length = 0
        while LoRa.available():
            LoRa.read()
            length += 1

        rssi = LoRa.packetRssi()
        snr  = LoRa.snr()
        print(f"PKT len={length:3d}  RSSI={rssi:7.2f} dBm  SNR={snr:6.2f} dB")

        status = LoRa.status()
        if status == LoRa.STATUS_CRC_ERR:    print("  !! CRC error")
        if status == LoRa.STATUS_HEADER_ERR: print("  !! Header error")

        LoRa.request(LoRa.RX_CONTINUOUS)
