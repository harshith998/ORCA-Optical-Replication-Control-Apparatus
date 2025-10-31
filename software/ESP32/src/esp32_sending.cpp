#include <Wire.h>
#include "Adafruit_VEML7700.h"

// Sensor pins
#define SDA1 9
#define SCL1 8
#define SDA2 4
#define SCL2 5

Adafruit_VEML7700 veml1 = Adafruit_VEML7700();
Adafruit_VEML7700 veml2 = Adafruit_VEML7700();
TwoWire I2C_1 = TwoWire(0);
TwoWire I2C_2 = TwoWire(1);

const unsigned long SAMPLE_MS = 500;
unsigned long lastSample = 0;


void setup() {
  Serial.begin(115200);
  
  // Initialize sensors
  I2C_1.begin(SDA1, SCL1);
  if (!veml1.begin(&I2C_1)) {
    Serial.println("Sensor 1 failed");
    while(1);
  }
  veml1.setGain(VEML7700_GAIN_1);
  veml1.setIntegrationTime(VEML7700_IT_100MS);
  
  I2C_2.begin(SDA2, SCL2);
  if (!veml2.begin(&I2C_2)) {
    Serial.println("Sensor 2 failed");
    while(1);
  }
  veml2.setGain(VEML7700_GAIN_1);
  veml2.setIntegrationTime(VEML7700_IT_100MS);
  
  delay(1000);  // Give receiver time to start
  lastSample = millis();
}

void loop() {
  unsigned long now = millis();
  if (now - lastSample >= SAMPLE_MS) {
    lastSample = now;
    
    // Read both sensors
    float lux1 = veml1.readLux();
    float lux2 = veml2.readLux();
    
    // Send as CSV: timestamp,lux1,lux2
    // REPLACE udp.beginPacket/print/endPacket with just println:
    Serial.print(now);
    Serial.print(",");
    Serial.print(lux1, 2);
    Serial.print(",");
    Serial.println(lux2, 2);
  }
}