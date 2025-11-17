#include "InputOutput.h"

InputOutput::InputOutput() : lcd(0x27, 16, 2), sw1(false), sw2(false),
                             potValue(0.0), luxValue(0) {}

void InputOutput::begin() {
  // Serial & I2C Setup
  Serial.begin(UART0_BAUD);
  Wire.begin(LCD_SDA, LCD_SCL);
  Wire.setClock(I2C_FREQUENCY);

  // LCD Init
  lcd.init();
  lcd.backlight();
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("ESP32 Init...");

  // Configure Pins
  pinMode(SWITCH1_PIN, INPUT_PULLUP);
  pinMode(SWITCH2_PIN, INPUT_PULLUP);
  pinMode(PWM_PIN, OUTPUT);

  // Configure PWM
  ledcSetup(PWM_CHANNEL, PWM_FREQ, PWM_RES_BITS);
  ledcAttachPin(PWM_PIN, PWM_CHANNEL);

  // Setup Complete
  delay(1000);
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("System Ready");
  Serial.println("==================");
  Serial.println("   System Ready   ");
  Serial.println("==================");
  delay(1000);
}

void InputOutput::update() {
  readSwitches();
  readAnalog();
  readUART();
}

void InputOutput::readSwitches() {
  sw1 = digitalRead(SWITCH1_PIN);
  sw2 = digitalRead(SWITCH2_PIN);
}

void InputOutput::readAnalog() {
  potValue = analogRead(SWITCH3_PIN) / 4095.0;
}

void InputOutput::readUART() {
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    luxValue = line.toFloat();
  }
}

void InputOutput::setPWM(float pwmValue) {
  ledcWrite(PWM_CHANNEL, pwmValue);
}

String InputOutput::toString() {
  String result = "[Switches] S1=";
  result += (sw1 ? "HIGH" : "LOW ");
  result += " S2=";
  result += (sw2 ? "HIGH" : "LOW ");
  result += " | [Analog] ";
  result += String(potValue);
  result += " | [Lux] ";
  result += String(luxValue);
  return result;
}

// IO methods
bool InputOutput::getSwitch1() { return sw1; }
bool InputOutput::getSwitch2() { return sw2; }
float  InputOutput::getAnalogValue() { return potValue; }
int  InputOutput::getLuxValue() { return luxValue; }
LiquidCrystal_I2C InputOutput::getLCD() { return lcd; }