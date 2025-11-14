#include <Arduino.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// ---------- Pin Definitions ----------
#define SWITCH1_PIN 14      // Input switch 1 with pull-up
#define SWITCH2_PIN 12      // Input switch 2 with pull-up
#define SWITCH3_PIN 27      // Potentiometer analog pin
#define PWM_PIN     25      // PWM output pin
#define LCD_SDA     21      // LCD SDA Pin
#define LCD_SCL     22      // LCD SCL Pin
#define UART0_BAUD  115200  // UART0 baud rate

// ---------- PWM Settings ----------
#define PWM_FREQ      5000   // 5 kHz PWM
#define PWM_CHANNEL   0      // PWM Channel
#define PWM_RES_BITS  10     // 10-bit (0–1023)
#define MAX_PWM_VALUE 1023   // Max for 10-bit

// ---------- LCD Setup ----------
LiquidCrystal_I2C lcd(0x27, 16, 2);  // Try 0x3F if no display

void setup() {
  // Serial & I2C
  Serial.begin(UART0_BAUD);
  Wire.begin(LCD_SDA, LCD_SCL);
  Wire.setClock(400000);

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

  // Scale potentiometer value to PWM range
  int pwmValue = map(potValue, 0, 4095, 0, MAX_PWM_VALUE);
  ledcWrite(PWM_CHANNEL, pwmValue);

  // -------- UART Read --------
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();

    // Parse if format like 252953,79.03,165.43
    int firstComma = line.indexOf(',');
    int secondComma = line.indexOf(',', firstComma + 1);

    if (firstComma != -1 && secondComma != -1) {
      float v1 = line.substring(firstComma + 1, secondComma).toFloat();
      float v2 = line.substring(secondComma + 1).toFloat();
      float avg = (v1 + v2) / 2.0;
      Serial.printf("[UART] Values: %.2f, %.2f | Avg: %.2f\n", v1, v2, avg);
    } else {
      Serial.print("[UART Raw] ");
      Serial.println(line);
    }
  }

  // -------- Serial Output Summary --------
  Serial.print("[Switches] S1=");
  Serial.print(sw1 ? "HIGH" : "LOW ");
  Serial.print(" S2=");
  Serial.print(sw2 ? "HIGH" : "LOW ");
  Serial.print(" | [Analog] ");
  Serial.print(potValue);
  Serial.print(" | [PWM] ");
  Serial.println(pwmValue);

  // -------- LCD Output --------
  lcd.setCursor(0, 0);
  lcd.print("S1:");
  lcd.print(sw1 ? "1" : "0");
  lcd.print(" S2:");
  lcd.print(sw2 ? "1" : "0");
  lcd.print(" PWM:");
  lcd.print(map(pwmValue, 0, MAX_PWM_VALUE, 0, 100));  // percentage

  lcd.setCursor(0, 1);
  lcd.print("A:");
  lcd.print(potValue);
  lcd.print("    ");  // clear tail

  delay(500);
}
