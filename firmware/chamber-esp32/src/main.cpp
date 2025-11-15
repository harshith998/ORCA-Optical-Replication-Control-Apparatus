#include <Arduino.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include "Config.h"

// Setup LCD over I2C
LiquidCrystal_I2C lcd(0x27, 16, 2);

void setup() {
  // Serial & I2C
  Serial.begin(UART0_BAUD);
  Wire.begin(LCD_SDA, LCD_SCL);
  Wire.setClock(100000);

  // LCD Init
  lcd.init();
  lcd.backlight();
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("ESP32 Test Start");

  // Configure pins
  pinMode(SWITCH1_PIN, INPUT_PULLUP);
  pinMode(SWITCH2_PIN, INPUT_PULLUP);
  pinMode(PWM_PIN, OUTPUT);

  // Configure PWM
  ledcSetup(PWM_CHANNEL, PWM_FREQ, PWM_RES_BITS);
  ledcAttachPin(PWM_PIN, PWM_CHANNEL);

  // Give startup info
  Serial.println("================================");
  Serial.println(" ESP32 Functional Pin Test");
  Serial.println("================================");
  delay(1500);

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("System Ready");
}

void loop() {
  // -------- Switch Reads --------
  bool sw1 = digitalRead(SWITCH1_PIN);
  bool sw2 = digitalRead(SWITCH2_PIN);

  // -------- Analog Read (0–4095 range) --------
  int potValue = analogRead(SWITCH3_PIN);

  // Other inputs
  int inputLux = 0; // Lux input

  // // -------- UART Read --------
  // if (Serial.available()) {
  //   String line = Serial.readStringUntil('\n');
  //   line.trim();

  //   // Parse if format like 252953,79.03,165.43
  //   // int firstComma = line.indexOf(',');
  //   // int secondComma = line.indexOf(',', firstComma + 1);

  //   // if (firstComma != -1 && secondComma != -1) {
  //   //   float v1 = line.substring(firstComma + 1, secondComma).toFloat();
  //   //   float v2 = line.substring(secondComma + 1).toFloat();
  //   //   float avg = (v1 + v2) / 2.0;
  //   //   Serial.printf("[UART] Values: %.2f, %.2f | Avg: %.2f\n", v1, v2, avg);
  //   // } else {
  //   //   Serial.print("[UART Raw] ");
  //   //   Serial.println(line);
  //   // }

  //   Serial.println(line);
  // }

  // UART Reader

  int pwmValue = map(potValue, 0, 4095, 0, MAX_PWM_VALUE);

  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    float val = line.toFloat();
    if (val > 5000) val = 5000;
    inputLux = val;

    if (sw1) {
      pwmValue = map(inputLux, 0, 5000, 0, MAX_PWM_VALUE);
    }
  }

  ledcWrite(PWM_CHANNEL, pwmValue);

  // -------- Serial Output Summary --------
  Serial.print("[Switches] S1=");
  Serial.print(sw1 ? "HIGH" : "LOW ");
  Serial.print(" S2=");
  Serial.print(sw2 ? "HIGH" : "LOW ");
  Serial.print(" | [Analog] ");
  Serial.print(potValue);
  Serial.print(" | [Lux] ");
  Serial.print(inputLux);
  Serial.print(" | [PWM] ");
  Serial.println(pwmValue);

  // -------- LCD Output --------
  // lcd.setCursor(0, 0);
  // lcd.print("S1:");
  // lcd.print(sw1 ? "1" : "0");
  // lcd.print(" S2:");
  // lcd.print(sw2 ? "1" : "0");
  // lcd.print(" PWM:");
  // lcd.print(map(pwmValue, 0, MAX_PWM_VALUE, 0, 100));  // percentage

  // lcd.setCursor(0, 1);
  // lcd.print("A:");
  // lcd.print(potValue);
  // lcd.print("    ");  // clear tail
  lcd.setCursor(0,0);
  lcd.print("    ");
  lcd.setCursor(0,0);
  lcd.print("Potato");

  while (!Serial.available()) {}
}
