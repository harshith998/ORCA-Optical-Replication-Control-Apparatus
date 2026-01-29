#include "InputOutput.h"

InputOutput::InputOutput() : lcd(0x27, 16, 2), sw1(false), sw2(false),
                             potValue(0.0), luxValue(0),
                             bufferIndex(0), bufferCount(0),
                             liveMin(0), liveMax(0) {
  for (int i = 0; i < LUX_BUFFER_SIZE; i++) {
    luxBuffer[i] = 0;
  }
}

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
float InputOutput::getAnalogValue() { return potValue; }
int InputOutput::getLuxValue() { return luxValue; }
LiquidCrystal_I2C InputOutput::getLCD() { return lcd; }

// Bounds buffer methods
void InputOutput::updateBounds() {
  if (bufferCount == 0) return;

  liveMin = luxBuffer[0];
  liveMax = luxBuffer[0];
  for (int i = 1; i < bufferCount; i++) {
    if (luxBuffer[i] < liveMin) liveMin = luxBuffer[i];
    if (luxBuffer[i] > liveMax) liveMax = luxBuffer[i];
  }
}

int InputOutput::getClampedLux(int rawLux) {
  // Add raw value to buffer (so system can adapt to real changes)
  luxBuffer[bufferIndex] = rawLux;
  bufferIndex = (bufferIndex + 1) % LUX_BUFFER_SIZE;
  if (bufferCount < LUX_BUFFER_SIZE) bufferCount++;

  // Update min/max bounds from buffer
  updateBounds();

  // First minute: no clamping, just return raw value
  if (bufferCount < LUX_BUFFER_SIZE) {
    return rawLux;
  }

  // Clamp to bounds
  if (rawLux < liveMin) return liveMin;
  if (rawLux > liveMax) return liveMax;
  return rawLux;
}