#include "InputOutput.h"

InputOutput::InputOutput() : lcd(0x27, 16, 2), sw1(false), sw2(false),
                             potValue(0), inputLux(0), pwmValue(0) {}

void InputOutput::begin() {
  // Serial & I2C setup
  Serial.begin(UART0_BAUD);
  Wire.begin(LCD_SDA, LCD_SCL);
  Wire.setClock(100000);

  // LCD setup
  lcd.init();
  lcd.backlight();
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("ESP32 Test Start");

  // Pin setup
  pinMode(SWITCH1_PIN, INPUT_PULLUP);
  pinMode(SWITCH2_PIN, INPUT_PULLUP);
  pinMode(PWM_PIN, OUTPUT);

  // PWM setup
  ledcSetup(PWM_CHANNEL, PWM_FREQ, PWM_RES_BITS);
  ledcAttachPin(PWM_PIN, PWM_CHANNEL);

  Serial.println("================================");
  Serial.println(" ESP32 Functional Pin Test");
  Serial.println("================================");
  delay(1500);

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("System Ready");
}

void InputOutput::update() {
  readSwitches();
  readAnalog();
  readUART();
  updatePWM();
  printSerialSummary();
  updateLCD();
}

void InputOutput::readSwitches() {
  sw1 = digitalRead(SWITCH1_PIN);
  sw2 = digitalRead(SWITCH2_PIN);
}

void InputOutput::readAnalog() {
  potValue = analogRead(SWITCH3_PIN);
}

void InputOutput::readUART() {
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    float val = line.toFloat();
    if (val > 5000) val = 5000;
    inputLux = val;
  }
}

void InputOutput::updatePWM() {
  pwmValue = map(potValue, 0, 4095, 0, MAX_PWM_VALUE);
  if (sw1) {
    pwmValue = map(inputLux, 0, 5000, 0, MAX_PWM_VALUE);
  }
  ledcWrite(PWM_CHANNEL, pwmValue);
}

void InputOutput::printSerialSummary() {
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
}

void InputOutput::updateLCD() {
  lcd.setCursor(0, 0);
  lcd.print("Pot: ");
  lcd.print(potValue);
  lcd.print("    ");
  lcd.setCursor(0, 1);
  lcd.print("PWM: ");
  lcd.print(map(pwmValue, 0, MAX_PWM_VALUE, 0, 100));
  lcd.print("%   ");
}

bool InputOutput::getSwitch1() { return sw1; }
bool InputOutput::getSwitch2() { return sw2; }
int  InputOutput::getAnalogValue() { return potValue; }
int  InputOutput::getLuxValue() { return inputLux; }
int  InputOutput::computePWM() { return pwmValue; }
