#include <Arduino.h>

// ---------- Pin Definitions ----------
#define SWITCH1_PIN 14      // Input switch with pull-up
#define PWM_PIN     25      // PWM output pin (GPIO25)
#define UART0_BAUD  115200  // UART0 baud rate

// ---------- PWM Settings ----------
#define PWM_FREQ     5000   // 5 kHz PWM
#define PWM_CHANNEL  0
#define PWM_RES_BITS 10     // 10-bit (0–1023)
#define MAX_PWM_VALUE 1023  // max value for 10-bit

void setup() {
  Serial.begin(UART0_BAUD);  // UART0 (GPIO3 RX, GPIO1 TX)
  pinMode(SWITCH1_PIN, INPUT_PULLUP);
  pinMode(PWM_PIN, OUTPUT);

  // Configure PWM
  ledcSetup(PWM_CHANNEL, PWM_FREQ, PWM_RES_BITS);
  ledcAttachPin(PWM_PIN, PWM_CHANNEL);

  Serial.println("ESP32 PWM control ready");
}

void loop() {
  // -------- Read UART0 RX3 line --------
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();

    // Example incoming line: "252953,79.03,165.43"
    // Split by commas
    int firstComma = line.indexOf(',');
    int secondComma = line.indexOf(',', firstComma + 1);

    if (firstComma != -1 && secondComma != -1) {
      String val1Str = line.substring(firstComma + 1, secondComma);
      String val2Str = line.substring(secondComma + 1);
      float val1 = val1Str.toFloat();
      float val2 = val2Str.toFloat();

      float avg = (val1 + val2) / 2.0;

      // Scale and cap
      float dutyValue = avg;               // scale directly (0–10 000 range)
      if (dutyValue > 10000) dutyValue = 10000;

      // Convert to PWM range
      int pwmOut = map((int)dutyValue, 0, 10000, 0, MAX_PWM_VALUE);

      // -------- Switch control --------
      if (digitalRead(SWITCH1_PIN) == HIGH) {
        ledcWrite(PWM_CHANNEL, pwmOut);
      } else {
        ledcWrite(PWM_CHANNEL, 0);  // Force output LOW
      }

      // Debug print
      Serial.print("Input avg: ");
      Serial.print(avg, 2);
      Serial.print("  -> PWM duty: ");
      Serial.println(pwmOut);
    }
  }
}
