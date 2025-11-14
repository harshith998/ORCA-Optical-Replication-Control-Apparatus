#include <Wire.h>
#include "Adafruit_VEML7700.h"

// I2C Sensor Pins
#define SDA1 21
#define SCL1 22
#define SDA2 33
#define SCL2 32

// 2 VEML7700 Sensors and Busses
Adafruit_VEML7700 veml1 = Adafruit_VEML7700();
Adafruit_VEML7700 veml2 = Adafruit_VEML7700();
TwoWire I2C_1 = TwoWire(0);
TwoWire I2C_2 = TwoWire(1);

// Transmission Timings
const unsigned long SAMPLE_MS = 20; // 50 Hz
const unsigned int baudRate = 115200; // Baud rate
unsigned long lastSample = 0;

void setup() {
  Serial.begin(baudRate);
  
  // Initialize sensors
  I2C_1.begin(SDA1, SCL1);
  if (!veml1.begin(&I2C_1)) {
    Serial.println("ERROR: Failed to initialize VEML7700-1");
    ESP.restart(); // Attempt to restart ESP32
  }
  veml1.setGain(VEML7700_GAIN_1);
  veml1.setIntegrationTime(VEML7700_IT_100MS);
  
  I2C_2.begin(SDA2, SCL2);
  if (!veml2.begin(&I2C_2)) {
    Serial.println("ERROR: Failed to initialize VEML7700-2");
    ESP.restart(); // Attempt to restart ESP32
  }
  veml2.setGain(VEML7700_GAIN_1);
  veml2.setIntegrationTime(VEML7700_IT_100MS);
  
  delay(1000);  // Give receiver time to start
  lastSample = millis();
}

void loop() {
  // Transmit data every SAMPLE_MS milliseconds
  unsigned long now = millis();
  if (now - lastSample >= SAMPLE_MS) {
    lastSample = now;
    
    // Read both sensors
    float lux1 = veml1.readLux();
    float lux2 = veml2.readLux();
    
    // Send as CSV: timestamp,lux1,lux2
    // Serial.print(now);
    // Serial.print(",");
    // Serial.print(lux1, 2);
    // Serial.print(",");
    // Serial.println(lux2, 2);

    // Send only average lux value between sensors
    Serial.println((lux1 + lux2)/2.0, 2);
    delay(100);
  }
}