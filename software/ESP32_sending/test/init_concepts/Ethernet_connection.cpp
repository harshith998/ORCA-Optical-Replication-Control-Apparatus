// ESP32 UDP sender (Arduino IDE)
// Replace Ethernet init with whichever driver your board needs.
// Uses Ethernet library + EthernetUDP class as example.

#include <SPI.h>
#include <Ethernet.h>
#include <EthernetUdp.h>

// MAC address for the ESP32 Ethernet interface (pick unique)
byte mac[] = { 0xDE, 0xAD, 0xBE, 0xEF, 0xFE, 0x11 };

// static IP for ESP32
IPAddress ip(192,168,50,11);

// Pi IP
IPAddress piIp(192,168,50,10);

// UDP ports
const unsigned int localPort = 4210;
const unsigned int remotePort = 4210;

EthernetUDP Udp;

void setup(){
  Serial.begin(115200);
  Ethernet.begin(mac, ip);
  delay(1000);
  Udp.begin(localPort);
  Serial.print("ESP32 IP: "); Serial.println(Ethernet.localIP());
}

void loop(){
  float va1 = 0.3; // replace with actual sensor reading
  // Format message
  char buf[32];
  int n = snprintf(buf, sizeof(buf), "va1:%0.3f\n", va1);

  // Send UDP packet to Pi
  Udp.beginPacket(piIp, remotePort);
  Udp.write((uint8_t*)buf, n);
  Udp.endPacket();

  //Serial.print("Sent: "); Serial.println(buf);

  delay(200); // 5 times/sec
}
