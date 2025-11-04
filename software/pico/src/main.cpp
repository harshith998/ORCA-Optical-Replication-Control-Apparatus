#include <Arduino.h>

/**
 * This code is intended to utilize the ADC capabilities of the Pi PICO
 * It converts an analog voltage reading on a specified GPIO (3.3V Max) to UART over the default TX pin
 */

 // Configuration Constants
const unsigned long SAMPLE_MS = 50; // 20 Hz sampling
const unsigned int baudRate = 115200; // Baud rate
unsigned long lastSample = 0;
const unsigned int analogPin = 26;

void setup() {
  Serial.begin(baudRate);
  delay(500); // Give serial time to initialize
}

void loop() {
  // Sample data every SAMPLE_MS milliseconds
  unsigned long currentTime = millis();
  if (currentTime - lastSample >= SAMPLE_MS) {
    lastSample = currentTime;

    // Read voltage from the analog pin and transmit over UART
    int raw = analogRead(analogPin);
    float voltage = raw * (3.3f / 4095.0f); // Convert to volts, 12-bit ADC (0–4095)
    Serial.println(voltage, 3);
  }
}
