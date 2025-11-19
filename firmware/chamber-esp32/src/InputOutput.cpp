#include "InputOutput.h"

#if ENABLE_FILTERING
// Comparator function for qsort
int InputOutput::cmpFloat(const void *a, const void *b) {
  float fa = *(const float*)a;
  float fb = *(const float*)b;
  if (fa < fb) return -1;
  if (fa > fb) return 1;
  return 0;
}

// Compute median of array
float InputOutput::computeMedian(float *arr, int n) {
  if (n == 0) return 0.0;
  float *tmp = (float*)malloc(sizeof(float)*n);
  for (int i = 0; i < n; i++) tmp[i] = arr[i];
  qsort(tmp, n, sizeof(float), cmpFloat);
  float med;
  if (n % 2 == 1) med = tmp[n/2];
  else med = 0.5 * (tmp[n/2 - 1] + tmp[n/2]);
  free(tmp);
  return med;
}

// Compute Median Absolute Deviation
float InputOutput::computeMAD(float *arr, int n, float median) {
  if (n == 0) return 0.0;
  float *dev = (float*)malloc(sizeof(float)*n);
  for (int i = 0; i < n; i++) dev[i] = fabs(arr[i] - median);
  float mad = computeMedian(dev, n);
  free(dev);
  return mad;
}

// Compute robust bounds using median and MAD with 3-sigma outlier rejection
void InputOutput::computeRobustBounds(float &outMin, float &outMax) {
  int n = calibBuffer.available();
  if (n == 0) { outMin = minLux; outMax = maxLux; return; }

  float *tmp = (float*)malloc(sizeof(float)*n);
  calibBuffer.copyChronological(tmp);

  float med = computeMedian(tmp, n);
  float mad = computeMAD(tmp, n, med);
  float sigma = 1.4826 * mad;
  float threshold = MAD_THRESHOLD * sigma;

  float inMin = 1e30, inMax = -1e30;
  int inCount = 0;

  for (int i = 0; i < n; i++) {
    float v = tmp[i];
    if (sigma > 1e-9) {
      if (fabs(v - med) <= threshold) {
        inCount++;
        if (v < inMin) inMin = v;
        if (v > inMax) inMax = v;
      }
    } else {
      inCount++;
      if (v < inMin) inMin = v;
      if (v > inMax) inMax = v;
    }
  }

  if (inCount == 0) {
    outMin = med;
    outMax = med;
  } else {
    outMin = inMin;
    outMax = inMax;
  }
  free(tmp);
}

// Apply selected filter to raw lux value
float InputOutput::applyFilter(float rawValue) {
  if (activeFilter == nullptr) return rawValue;
  return activeFilter->process(rawValue);
}

// Update dynamic bounds based on 5-minute history with outlier rejection
void InputOutput::updateDynamicBounds() {
  float newMin, newMax;
  computeRobustBounds(newMin, newMax);

  // Smooth blending to prevent sudden jumps
  minLux = (1.0 - BOUNDS_ALPHA) * minLux + BOUNDS_ALPHA * newMin;
  maxLux = (1.0 - BOUNDS_ALPHA) * maxLux + BOUNDS_ALPHA * newMax;

  // Ensure sensible span (minimum 1.0 lux difference)
  if (maxLux <= minLux + 1e-3) {
    maxLux = minLux + 1.0;
  }
}
#endif

InputOutput::InputOutput() : lcd(0x27, 16, 2), sw1(false), sw2(false),
                             potValue(0.0), luxValue(0)
#if ENABLE_FILTERING
                             , calibBuffer(CALIB_WINDOW_SIZE), minLux(0.0), maxLux(10000.0),
                             lastBoundsUpdate(0), activeFilter(nullptr)
#endif
{}

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

#if ENABLE_FILTERING
  // Initialize filter based on FILTER_TYPE config
  if (FILTER_TYPE == 1) {
    activeFilter = new SMAFilter(SMA_WINDOW);
  } else if (FILTER_TYPE == 2) {
    activeFilter = new EMAFilter(EMA_ALPHA);
  } else if (FILTER_TYPE == 3) {
    activeFilter = new SGFilter(SG_WINDOW, SG_POLY_ORDER);
  }
  lastBoundsUpdate = millis();
#endif

  // Setup Complete
  delay(1000);
  lcd.clear();
  lcd.setCursor(0, 0);
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
    float rawLux = line.toFloat();

#if ENABLE_FILTERING
    // Apply filter to raw lux value
    float filteredLux = applyFilter(rawLux);

    // Add to calibration buffer
    calibBuffer.add(filteredLux);

    // Update dynamic bounds periodically (every ~5 seconds for responsiveness)
    unsigned long now = millis();
    if (now - lastBoundsUpdate >= 5000) {
      lastBoundsUpdate = now;
      updateDynamicBounds();
    }

    // Normalize filtered lux using dynamic bounds, store as [0-1] * 10000
    if (maxLux <= minLux + 1e-3) {
      luxValue = 0;  // Bounds are invalid, return minimum
    } else {
      float normalized = (filteredLux - minLux) / (maxLux - minLux);
      if (normalized < 0.0f) normalized = 0.0f;
      if (normalized > 1.0f) normalized = 1.0f;
      luxValue = (int)(normalized * 10000.0f + 0.5f);  // Store as [0-10000] for main.cpp
    }
#else
    // No filtering: use raw lux value directly
    luxValue = (int)rawLux;
#endif
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