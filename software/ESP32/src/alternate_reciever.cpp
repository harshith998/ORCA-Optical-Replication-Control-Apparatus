#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include "Adafruit_VEML7700.h"

// === I2C Pin Definitions ===
#define SDA1 9   // First sensor I2C pins
#define SCL1 8
#define SDA2 4   // Second sensor I2C pins  
#define SCL2 5

// === LCD Configuration ===
#define LCD_COLS 16
#define LCD_ROWS 2
#define LCD_I2C_ADDRESS 0x27  // Common I2C address, might be 0x3F

#define LED_PIN 25              // PWM compatible
#define SWITCH_LED_ONOFF 14
#define SWITCH_AUTO_MANUAL 27

// === LED Configuration ===
#define PWM_CHANNEL 0
#define PWM_FREQ 5000  // 5kHz
#define PWM_RESOLUTION 10
#define MAX_PWM_VALUE 1023



// === Potentiometer Configuration ===
#define POT_PIN 34  // ADC1 channel (GPIO 34 is ADC1_CH6)

// === Timing Configuration ===
const unsigned long SAMPLE_MS = 500;  //2Hz sampling
const int WINDOW_SIZE = 600;          // 5 minutes @ 500ms -> 600 samples
const float BOUNDS_ALPHA = 0.05;
const unsigned long LCD_UPDATE_MS = 500;

// === Sensor Objects ===
Adafruit_VEML7700 veml1 = Adafruit_VEML7700();
Adafruit_VEML7700 veml2 = Adafruit_VEML7700();
TwoWire I2C_1 = TwoWire(0);  // First I2C bus
TwoWire I2C_2 = TwoWire(1);  // Second I2C bus


LiquidCrystal_I2C lcd(LCD_I2C_ADDRESS, LCD_COLS, LCD_ROWS);


float minLux = 0.0;
float maxLux = 1000.0;


struct CircularBuffer {
  int size;
  int idx;
  int count;
  float *buf;
  
  CircularBuffer(int n = 0) {
    size = n;
    idx = 0;
    count = 0;
    if (n > 0) buf = (float*)malloc(sizeof(float) * n);
    else buf = nullptr;
  }
  
  ~CircularBuffer() { if (buf) free(buf); }
  
  void add(float v) {
    if (!buf) return;
    buf[idx] = v;
    idx = (idx + 1) % size;
    if (count < size) count++;
  }
  
  int available() { return count; }
  
  void copyChronological(float *dest) {
    if (!buf) return;
    int start = (count == size) ? idx : 0;
    int n = count;
    for (int i = 0; i < n; ++i) {
      int src = (start + i) % size;
      dest[i] = buf[src];
    }
  }
};

// === Filter Base Class ===
struct Filter {
  virtual float process(float value) = 0;
};

// === Simple Moving Average Filter ===
struct SMAFilter : public Filter {
  int N;
  float *window;
  int pos;
  int count;
  float sum;
  
  SMAFilter(int windowSize = 5) {
    N = windowSize;
    window = (float*)malloc(sizeof(float) * N);
    pos = 0; count = 0; sum = 0.0;
    for (int i=0;i<N;i++) window[i]=0.0;
  }
  
  ~SMAFilter(){ free(window); }
  
  float process(float value) override {
    if (count < N) {
      window[pos] = value;
      sum += value;
      pos = (pos + 1) % N;
      count++;
      return sum / count;
    } else {
      sum -= window[pos];
      window[pos] = value;
      sum += value;
      pos = (pos + 1) % N;
      return sum / N;
    }
  }
};

// === Exponential Moving Average Filter ===
struct EMAFilter : public Filter {
  float alpha;
  bool initialized;
  float state;
  
  EMAFilter(float a = 0.1) { 
    alpha = a; 
    initialized = false; 
    state = 0.0; 
  }
  
  float process(float value) override {
    if (!initialized) { 
      state = value; 
      initialized = true; 
      return state; 
    }
    state = alpha * value + (1.0 - alpha) * state;
    return state;
  }
};

// === Savitzky-Golay Filter ===
// precomputing convolution coefficients in matrix for given window size and polynomial order
// allows more efficient filtering while retaining smoothing and derivative estimation properties from least squares polynomial fitting
struct SGFilter : public Filter {
  int window;
  int polyOrder;
  int half;
  float *coeffs;
  float *buffer;
  int pos;
  int filled;
  
  SGFilter(int w = 11, int p = 3) {
    if (w % 2 == 0) w += 1;
    window = w;
    polyOrder = p;
    half = (window - 1) / 2;
    coeffs = (float*)malloc(sizeof(float) * window);
    buffer = (float*)malloc(sizeof(float) * window);
    pos = 0; filled = 0;
    for (int i=0;i<window;i++){ buffer[i]=0.0; coeffs[i]=0.0; }
    computeCoefficients();
  }
  
  ~SGFilter(){ free(coeffs); free(buffer); }

  bool invertMatrix(double *mat, double *inv, int n) {
    double *aug = (double*)malloc(sizeof(double) * n * 2 * n);
    if (!aug) return false;
    
    for (int r=0;r<n;r++){
      for (int c=0;c<n;c++) aug[r*(2*n)+c] = mat[r*n + c];
      for (int c=0;c<n;c++) aug[r*(2*n)+n + c] = (r==c) ? 1.0 : 0.0;
    }
    
    for (int col=0; col<n; ++col) {
      int pivot = col;
      double maxval = fabs(aug[pivot*(2*n) + col]);
      for (int r=col+1; r<n; ++r) {
        double v = fabs(aug[r*(2*n) + col]);
        if (v > maxval) { maxval = v; pivot = r; }
      }
      if (maxval < 1e-12) { free(aug); return false; }
      
      if (pivot != col) {
        for (int c=0;c<2*n;c++) {
          double tmp = aug[col*(2*n)+c];
          aug[col*(2*n)+c] = aug[pivot*(2*n)+c];
          aug[pivot*(2*n)+c] = tmp;
        }
      }
      
      double pv = aug[col*(2*n) + col];
      for (int c=0;c<2*n;c++) aug[col*(2*n)+c] /= pv;
      
      for (int r=0;r<n;r++){
        if (r==col) continue;
        double factor = aug[r*(2*n) + col];
        if (fabs(factor) < 1e-15) continue;
        for (int c=0;c<2*n;c++){
          aug[r*(2*n)+c] -= factor * aug[col*(2*n)+c];
        }
      }
    }
    
    for (int r=0;r<n;r++){
      for (int c=0;c<n;c++){
        inv[r*n + c] = aug[r*(2*n) + n + c];
      }
    }
    free(aug);
    return true;
  }

  void computeCoefficients() {
    int rows = window;
    int cols = polyOrder + 1;
    double *A = (double*)malloc(sizeof(double)*rows*cols);
    
    for (int r=0; r<rows; ++r) {
      int j = r - half;
      double val = 1.0;
      for (int p=0; p<cols; ++p) {
        A[r*cols + p] = val;
        val *= (double)j;
      }
    }
    
    double *ATA = (double*)malloc(sizeof(double)*cols*cols);
    for (int i=0;i<cols*cols;i++) ATA[i]=0.0;
    for (int i=0;i<cols;i++){
      for (int j=0;j<cols;j++){
        double s = 0.0;
        for (int r=0;r<rows;r++) s += A[r*cols + i] * A[r*cols + j];
        ATA[i*cols + j] = s;
      }
    }
    
    double *invATA = (double*)malloc(sizeof(double)*cols*cols);
    bool ok = invertMatrix(ATA, invATA, cols);
    
    if (!ok) {
      float avg = 1.0 / window;
      for (int i=0;i<window;i++) coeffs[i] = avg;
      free(A); free(ATA); free(invATA);
      return;
    }
    
    double *AT = (double*)malloc(sizeof(double)*cols*rows);
    for (int i=0;i<cols;i++){
      for (int r=0;r<rows;r++) AT[i*rows + r] = A[r*cols + i];
    }
    
    double *B = (double*)malloc(sizeof(double)*cols*rows);
    for (int i=0;i<cols;i++){
      for (int j=0;j<rows;j++){
        double s = 0.0;
        for (int k=0;k<cols;k++) s += invATA[i*cols + k] * AT[k*rows + j];
        B[i*rows + j] = s;
      }
    }
    
    for (int j=0;j<rows;j++) coeffs[j] = (float)B[0*rows + j];

    free(A); free(ATA); free(invATA); free(AT); free(B);
  }

  float process(float value) override {
    buffer[pos] = value;
    pos = (pos + 1) % window;
    if (filled < window) filled++;

    if (filled < window) {
      float s = 0.0;
      int n = filled;
      for (int i=0;i<n;i++) s += buffer[i];
      return s / n;
    }

    float sum = 0.0;
    int start = pos;
    for (int i=0;i<window;i++){
      int idx = (start + i) % window;
      sum += coeffs[i] * buffer[idx];
    }
    return sum;
  }
};

// === Filter Instances ===
SMAFilter sma(11);
EMAFilter ema(0.1);
SGFilter sg(11, 3);

// Choose filter: 0=SMA, 1=EMA, 2=SG
int activeFilter = 1;

CircularBuffer calibBuffer(WINDOW_SIZE);

// === Timing Variables ===
unsigned long lastSample = 0;
unsigned long lastLCDUpdate = 0;

// === Display Variables ===
float lastLuxValue = 0.0;

// === Helper Functions ===
int cmpFloat(const void *a, const void *b) {
  float fa = *(const float*)a;
  float fb = *(const float*)b;
  if (fa < fb) return -1;
  if (fa > fb) return 1;
  return 0;
}

float computeMedian(float *arr, int n) {
  if (n == 0) return 0.0;
  float *tmp = (float*)malloc(sizeof(float)*n);
  for (int i=0;i<n;i++) tmp[i] = arr[i];
  qsort(tmp, n, sizeof(float), cmpFloat);
  float med;
  if (n % 2 == 1) med = tmp[n/2];
  else med = 0.5 * (tmp[n/2 - 1] + tmp[n/2]);
  free(tmp);
  return med;
}

float computeMAD(float *arr, int n, float median) {
  if (n == 0) return 0.0;
  float *dev = (float*)malloc(sizeof(float)*n);
  for (int i=0;i<n;i++) dev[i] = fabs(arr[i] - median);
  float mad = computeMedian(dev, n);
  free(dev);
  return mad;
}

void computeRobustBounds(float &outMin, float &outMax) {
  int n = calibBuffer.available();
  if (n == 0) { outMin = minLux; outMax = maxLux; return; }
  
  float *tmp = (float*)malloc(sizeof(float)*n);
  calibBuffer.copyChronological(tmp);

  float med = computeMedian(tmp, n);
  float mad = computeMAD(tmp, n, med);
  float sigma = 1.4826 * mad;
  float threshold = 3.0 * sigma;
  
  float inMin = 1e30, inMax = -1e30;
  int inCount = 0;
  
  for (int i=0;i<n;i++) {
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

float mapFloat(float x, float inMin, float inMax, float outMin, float outMax) {
  if (inMax <= inMin) return outMin;
  float t = (x - inMin) / (inMax - inMin);
  if (t < 0.0) t = 0.0;
  if (t > 1.0) t = 1.0;
  return outMin + t * (outMax - outMin);
}

// === Read potentiometer ===
int readPotentiometer() {
  int rawValue = analogRead(POT_PIN);  // 0-4095 (12-bit ADC)
  int brightness = map(rawValue, 0, 4095, 0, 1023);
  return brightness;
}

// === Update LCD ===
void updateLCD(bool ledOn, bool autoMode, float luxValue) {
  lcd.clear();
  
  // Line 1: Status
  lcd.setCursor(0, 0);
  lcd.print("LED:");
  lcd.print(ledOn ? "ON " : "OFF");
  lcd.print(" ");
  lcd.print(autoMode ? "AUTO" : "MAN");
  
  // Line 2: Lux value
  lcd.setCursor(0, 1);
  lcd.print("Lux: ");
  lcd.print(luxValue, 1);
}


void setup() {
  Serial.begin(115200);
  
  // Initialize switches
  pinMode(SWITCH_LED_ONOFF, INPUT_PULLUP);
  pinMode(SWITCH_AUTO_MANUAL, INPUT_PULLUP);
  
  // Initialize potentiometer
  pinMode(POT_PIN, INPUT);
  analogSetAttenuation(ADC_11db);  // 0-3.3V range
  
  // Initialize I2C sensors
  I2C_1.begin(SDA1, SCL1);
  if (!veml1.begin(&I2C_1)) {
    Serial.println("VEML7700 #1 not found");
    while (1);
  }
  veml1.setGain(VEML7700_GAIN_1);
  veml1.setIntegrationTime(VEML7700_IT_100MS);

  I2C_2.begin(SDA2, SCL2);
  if (!veml2.begin(&I2C_2)) {
    Serial.println("VEML7700 #2 not found");
    while (1);
  }
  veml2.setGain(VEML7700_GAIN_1);
  veml2.setIntegrationTime(VEML7700_IT_100MS);

  // Initialize PWM for LED
  ledcSetup(PWM_CHANNEL, PWM_FREQ, PWM_RESOLUTION);
  ledcAttachPin(LED_PIN, PWM_CHANNEL);
  ledcWrite(PWM_CHANNEL, 0);  // Start with LED off
  
  // Initialize LCD
  lcd.init();
  lcd.backlight();
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Initializing...");
  
  delay(2000);
  
  Serial.println("System initialized.");
  Serial.println("Format: timestamp,lux1,lux2");
  
  lastSample = millis();
  lastLCDUpdate = millis();
}


void loop() {
  unsigned long now = millis();
  
  // Read switches (LOW = pressed/ON with pull-up resistors)
  bool ledSwitchOn = (digitalRead(SWITCH_LED_ONOFF) == HIGH);
  bool autoMode = (digitalRead(SWITCH_AUTO_MANUAL) == LOW);
  
  // === AUTO MODE ===
  if (autoMode && (now - lastSample >= SAMPLE_MS)) {
    lastSample = now;
    
    // Read sensors
    float lux1 = veml1.readLux();
    float lux2 = veml2.readLux();
    float rawLux = (lux1 + lux2) / 2.0;
    
    // Send to serial in Python-expected format
    Serial.print(now);
    Serial.print(",");
    Serial.print(lux1, 2);
    Serial.print(",");
    Serial.println(lux2, 2);
    
    // Apply filter
    float filtered;
    if (activeFilter == 0) filtered = sma.process(rawLux);
    else if (activeFilter == 1) filtered = ema.process(rawLux);
    else filtered = sg.process(rawLux);
    
    // Add to calibration buffer
    calibBuffer.add(filtered);
    
    // Compute robust bounds
    float newMin, newMax;
    computeRobustBounds(newMin, newMax);
    
    // Smooth blending
    minLux = (1.0 - BOUNDS_ALPHA) * minLux + BOUNDS_ALPHA * newMin;
    maxLux = (1.0 - BOUNDS_ALPHA) * maxLux + BOUNDS_ALPHA * newMax;
    
    // Ensure sensible span
    if (maxLux <= minLux + 1e-3) {
      maxLux = minLux + 1.0;
    }
    
    // Map to PWM
    float mapped = mapFloat(filtered, minLux, maxLux, 0.0, 1023.0);
    int pwm = (int)round(mapped);
    if (pwm < 0) pwm = 0;
    if (pwm > 1023) pwm = 1023;
    
    // Apply LED brightness based on switch
    if (ledSwitchOn) {
      ledcWrite(PWM_CHANNEL, pwm);
    } else {
      ledcWrite(PWM_CHANNEL, 0);
    }
    
    lastLuxValue = filtered;
  }
  
  // === MANUAL MODE ===
  else if (!autoMode) {
    int potBrightness = readPotentiometer();
    
    // Apply LED brightness based on switch
    if (ledSwitchOn) {
      ledcWrite(PWM_CHANNEL, potBrightness);
    } else {
      ledcWrite(PWM_CHANNEL, 0);
    }
    
    lastLuxValue = (float)potBrightness;
  }
  
  // === UPDATE LCD ===
  if (now - lastLCDUpdate >= LCD_UPDATE_MS) {
    updateLCD(ledSwitchOn, autoMode, lastLuxValue);
    lastLCDUpdate = now;
  }
  
  delay(10);//optional delay
}