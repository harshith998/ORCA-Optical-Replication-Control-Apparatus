#include "BluetoothSerial.h"
#include <Wire.h>
#include "Adafruit_VEML7700.h"

BluetoothSerial SerialBT;
Adafruit_VEML7700 veml1 = Adafruit_VEML7700();
Adafruit_VEML7700 veml2 = Adafruit_VEML7700();
TwoWire I2C_1 = TwoWire(0);
TwoWire I2C_2 = TwoWire(1);

#define SDA1 9
#define SCL1 8
#define SDA2 4
#define SCL2 5

void setup() {
  Serial.begin(115200);  // Still useful for debugging
  SerialBT.begin("ESP32_Lux_Sensor");  // Bluetooth name
  
  I2C_1.begin(SDA1, SCL1);
  I2C_2.begin(SDA2, SCL2);
  
  if (!veml1.begin(&I2C_1)) {
    Serial.println("Sensor 1 failed");
    SerialBT.println("Sensor 1 failed");
    while(1);
  }
  
  if (!veml2.begin(&I2C_2)) {
    Serial.println("Sensor 2 failed");
    SerialBT.println("Sensor 2 failed");
    while(1);
  }
  
  veml1.setGain(VEML7700_GAIN_1);
  veml1.setIntegrationTime(VEML7700_IT_100MS);
  veml2.setGain(VEML7700_GAIN_1);
  veml2.setIntegrationTime(VEML7700_IT_100MS);
  
  SerialBT.println("Ready!");
}

void loop() {
  float lux1 = veml1.readLux();
  float lux2 = veml2.readLux();
  float avgLux = (lux1 + lux2) / 2.0;
  
  // Send to both USB and Bluetooth
  String data = String(millis()) + "," + String(lux1) + "," + String(lux2) + "," + String(avgLux);
  Serial.println(data);
  SerialBT.println(data);
  
  delay(500);  // 500ms = 2Hz sampling
}