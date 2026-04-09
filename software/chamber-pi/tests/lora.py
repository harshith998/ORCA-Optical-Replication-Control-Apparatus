import os, sys
currentdir = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.dirname(os.path.dirname(currentdir)))
from LoRaRF import SX126x
import time

# Begin LoRa radio: SPI bus 0, CE1 (spidev0.1), reset=BCM8, busy=BCM20, irq/DIO1=BCM21
LoRa = SX126x()
print("Begin LoRa radio")
if not LoRa.begin(0, 1, 8, 20, -1) :
    raise Exception("Something wrong, can't begin LoRa radio")

# Set frequency to 915 Mhz
print("Set frequency to 915 Mhz")
LoRa.setFrequency(915000000)

# Set RX gain to power saving gain
print("Set RX gain to power saving gain")
LoRa.setRxGain(LoRa.RX_GAIN_POWER_SAVING)

# Configure modulation parameter including spreading factor (SF), bandwidth (BW), and coding rate (CR)
print("Set modulation parameters:\n\tSpreading factor = 9\n\tBandwidth = 250 kHz\n\tCoding rate = 4/7")
sf = 9
bw = 250000
cr = 7
LoRa.setLoRaModulation(sf, bw, cr)

# Configure packet parameter including header type, preamble length, payload length, and CRC type
print("Set packet parameters:\n\tExplicit header type\n\tPreamble length = 12\n\tPayload Length = 15\n\tCRC on")
headerType = LoRa.HEADER_EXPLICIT
preambleLength = 12
payloadLength = 15
crcType = True
LoRa.setLoRaPacket(headerType, preambleLength, payloadLength, crcType)

# Set syncronize word for public network (0x3444)
print("Set syncronize word to 0x1424 (private, matches satellite 0x12)")
LoRa.setSyncWord(0x1424)

print("\n-- LoRa Receiver Continuous --\n")

# Request for receiving new LoRa packet in RX continuous mode
LoRa.request(LoRa.RX_CONTINUOUS)

# Receive message continuously
while True :

    # Check for incoming LoRa packet
    if LoRa.available() :

        # Put received packet to message and counter variable
        message = ""
        while LoRa.available() > 1 :
            message += chr(LoRa.read())
        counter = LoRa.read()

        # Print received message and counter in serial
        print(f"{message}  {counter}")

        # Print packet/signal status including RSSI, SNR, and signalRSSI
        print("Packet status: RSSI = {0:0.2f} dBm | SNR = {1:0.2f} dB".format(LoRa.packetRssi(), LoRa.snr()))

        # Show received status in case CRC or header error occur
        status = LoRa.status()
        if status == LoRa.STATUS_CRC_ERR : print("CRC error")
        if status == LoRa.STATUS_HEADER_ERR : print("Packet header error")

        # Re-enter RX continuous mode for next packet
        LoRa.request(LoRa.RX_CONTINUOUS)