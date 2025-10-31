#include <Wire.h>

#define SDA1 4   // First I2C SDA pin pair
#define SCL1 5
#define SDA2 6   // Second I2C SDA pin pair
#define SCL2 7

void scanI2C() {
  Serial.println("Scanning I2C bus...");
  byte error, address;
  int nDevices = 0;

  for (address = 1; address < 127; address++) {
    Wire.beginTransmission(address);
    error = Wire.endTransmission();

    if (error == 0) {
      Serial.print("I2C device found at address 0x");
      if (address < 16) Serial.print("0");
      Serial.print(address, HEX);
      Serial.println(" !");
      nDevices++;
    } else if (error == 4) {
      Serial.print("Unknown error at address 0x");
      if (address < 16) Serial.print("0");
      Serial.println(address, HEX);
    }
  }

  if (nDevices == 0)
    Serial.println("No I2C devices found\n");
  else
    Serial.println("Scan complete.\n");
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("Dynamic I2C pin switching demo!");
}

void loop() {
  // Use first I2C pin pair
  Serial.println("=== Using I2C pins SDA=" + String(SDA1) + ", SCL=" + String(SCL1) + " ===");
  Wire.begin(SDA1, SCL1);
  delay(100);
  scanI2C();

  delay(3000);

  // Use second I2C pin pair
  Serial.println("=== Switching to I2C pins SDA=" + String(SDA2) + ", SCL=" + String(SCL2) + " ===");
  Wire.begin(SDA2, SCL2);
  delay(100);
  scanI2C();

  delay(3000);
}
