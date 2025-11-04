#include <Arduino.h>

void setup() {
  Serial.begin(115200);
  delay(500); // Give serial time to initialize
}

void loop() {
  int raw = analogRead(26);               // GP26 (A0) = ADC0
  float voltage = raw * (3.3f / 4095.0f); // Convert to volts, 12-bit ADC (0–4095)
//   Serial.print("Voltage: ");
  Serial.println(voltage, 3);
  delay(100); // 10 Hz update
}
