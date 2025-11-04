#include <Wire.h>
#include "Adafruit_VEML7700.h"

#define SDA1 9   // First sensor I2C pins
#define SCL1 8
#define SDA2 4   // Second sensor I2C pins  
#define SCL2 5

Adafruit_VEML7700 veml1 = Adafruit_VEML7700();
Adafruit_VEML7700 veml2 = Adafruit_VEML7700();
TwoWire I2C_1 = TwoWire(0);  // First I2C bus
TwoWire I2C_2 = TwoWire(1);  // Second I2C bus


// 5 minute sliding window moving bound calibration
// outlier removal via median+MAD
//modular filters: 
//Simple Moving Average,
//Exponential Moving Average, 
// Savitzky-Golay (fitted curve)

// === CONFIG ===
const int LED_PIN = 5;                // PWM-capable pin
const unsigned long SAMPLE_MS = 500;  // sample interval -> 500ms => 5Hz
const int WINDOW_SIZE = 600;         // 5 minutes @ 500ms -> 600 samples

// Initial manual bounds (can be tuned before the system converges)
float minLux = 0.0;
float maxLux = 1000.0;

// How quickly min/max bounds blend to newly computed bounds (0..1)
const float BOUNDS_ALPHA = 0.05;

// === Circular buffer utility ===
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
  // copy contents into dest array in chronological order (oldest..newest)
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

// === Filter abstract base ===
struct Filter {
  virtual float process(float value) = 0;
};

// === Simple Moving Average (true) ===
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

// === Exponential Moving Average (true) ===
struct EMAFilter : public Filter {
  float alpha;
  bool initialized;
  float state;
  EMAFilter(float a = 0.1) { alpha = a; initialized = false; state = 0.0; }
  float process(float value) override {
    if (!initialized) { state = value; initialized = true; return state; }
    state = alpha * value + (1.0 - alpha) * state;
    return state;
  }
};

// === Savitzky-Golay Filter===
// Computes smoothing convolution coefficients in setup using least-squares,
// then performs convolution over a circular buffer.
struct SGFilter : public Filter {
  int window;        // must be odd (2m+1)
  int polyOrder;     // polynomial degree
  int half;
  float *coeffs;     // length window, convolution coefficients (centered)
  float *buffer;     // circular buffer for raw values
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

  // Small matrix utilities for Gauss-Jordan inversion (square matrices)
  bool invertMatrix(double *mat, double *inv, int n) {
    // mat: row-major n*n. inv returns inverse in row-major.
    // Use Gauss-Jordan on augmented matrix [mat | I]
    double *aug = (double*)malloc(sizeof(double) * n * 2 * n);
    if (!aug) return false;
    // build augmented
    for (int r=0;r<n;r++){
      for (int c=0;c<n;c++) aug[r*(2*n)+c] = mat[r*n + c];
      for (int c=0;c<n;c++) aug[r*(2*n)+n + c] = (r==c) ? 1.0 : 0.0;
    }
    // Gauss-Jordan
    for (int col=0; col<n; ++col) {
      // find pivot
      int pivot = col;
      double maxval = fabs(aug[pivot*(2*n) + col]);
      for (int r=col+1; r<n; ++r) {
        double v = fabs(aug[r*(2*n) + col]);
        if (v > maxval) { maxval = v; pivot = r; }
      }
      if (maxval < 1e-12) { free(aug); return false; } // singular
      // swap if needed
      if (pivot != col) {
        for (int c=0;c<2*n;c++) {
          double tmp = aug[col*(2*n)+c];
          aug[col*(2*n)+c] = aug[pivot*(2*n)+c];
          aug[pivot*(2*n)+c] = tmp;
        }
      }
      // normalize pivot row
      double pv = aug[col*(2*n) + col];
      for (int c=0;c<2*n;c++) aug[col*(2*n)+c] /= pv;
      // eliminate other rows
      for (int r=0;r<n;r++){
        if (r==col) continue;
        double factor = aug[r*(2*n) + col];
        if (fabs(factor) < 1e-15) continue;
        for (int c=0;c<2*n;c++){
          aug[r*(2*n)+c] -= factor * aug[col*(2*n)+c];
        }
      }
    }
    // copy inverse from right half
    for (int r=0;r<n;r++){
      for (int c=0;c<n;c++){
        inv[r*n + c] = aug[r*(2*n) + n + c];
      }
    }
    free(aug);
    return true;
  }

  void computeCoefficients() {
    // Build A matrix: (window x (polyOrder+1)), rows j=-half..half, cols p=0..polyOrder: j^p
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
    // Compute ATA = A^T * A  -> size cols x cols
    double *ATA = (double*)malloc(sizeof(double)*cols*cols);
    for (int i=0;i<cols*cols;i++) ATA[i]=0.0;
    for (int i=0;i<cols;i++){
      for (int j=0;j<cols;j++){
        double s = 0.0;
        for (int r=0;r<rows;r++) s += A[r*cols + i] * A[r*cols + j];
        ATA[i*cols + j] = s;
      }
    }
    // invert ATA
    double *invATA = (double*)malloc(sizeof(double)*cols*cols);
    bool ok = invertMatrix(ATA, invATA, cols);
    if (!ok) {
      // fallback: set smoothing to simple average coefficients
      float avg = 1.0 / window;
      for (int i=0;i<window;i++) coeffs[i] = avg;
      free(A); free(ATA); free(invATA);
      return;
    }
    // Compute AT (cols x rows) = transpose of A
    double *AT = (double*)malloc(sizeof(double)*cols*rows);
    for (int i=0;i<cols;i++){
      for (int r=0;r<rows;r++) AT[i*rows + r] = A[r*cols + i];
    }
    // B = invATA * AT  -> size (cols x rows)
    double *B = (double*)malloc(sizeof(double)*cols*rows);
    for (int i=0;i<cols;i++){
      for (int j=0;j<rows;j++){
        double s = 0.0;
        for (int k=0;k<cols;k++) s += invATA[i*cols + k] * AT[k*rows + j];
        B[i*rows + j] = s;
      }
    }
    // smoothing coefficients for center estimate are row 0 of B (row index 0)
    for (int j=0;j<rows;j++) coeffs[j] = (float)B[0*rows + j];

    free(A); free(ATA); free(invATA); free(AT); free(B);
  }

  float process(float value) override {
    // push value
    buffer[pos] = value;
    pos = (pos + 1) % window;
    if (filled < window) filled++;

    // not enough data: return simple average
    if (filled < window) {
      float s = 0.0;
      int n = filled;
      for (int i=0;i<n;i++) s += buffer[i];
      return s / n;
    }

    // perform convolution centered: coefficients are aligned with chronological buffer starting at pos (oldest)
    // build chronological array: oldest..newest
    float sum = 0.0;
    int start = pos; // position of oldest
    for (int i=0;i<window;i++){
      int idx = (start + i) % window;   // i from 0..window-1 corresponds to j=-half..+half
      sum += coeffs[i] * buffer[idx];
    }
    return sum;
  }
};

// === Globals for filters and calibration buffer ===
SMAFilter sma(11);          // example SMA window 11
EMAFilter ema(0.1);         // example alpha
SGFilter sg(11, 3);         // SG window 11, poly 3

// choose which filter to use: 0=SMA,1=EMA,2=SG
int activeFilter = 1;

CircularBuffer calibBuffer(WINDOW_SIZE); // stores last WINDOW_SIZE filtered readings

unsigned long lastSample = 0;

// === Helpers: median, MAD, min/max from inliers ===
int cmpFloat(const void *a, const void *b) {
  float fa = *(const float*)a;
  float fb = *(const float*)b;
  if (fa < fb) return -1;
  if (fa > fb) return 1;
  return 0;
}

float computeMedian(float *arr, int n) {
  if (n == 0) return 0.0;
  // copy to temp and sort
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

// robust inlier-min/max using median+MAD
void computeRobustBounds(float &outMin, float &outMax) {
  int n = calibBuffer.available();
  if (n == 0) { outMin = minLux; outMax = maxLux; return; }
  float *tmp = (float*)malloc(sizeof(float)*n);
  calibBuffer.copyChronological(tmp); // chronological oldest..newest

  float med = computeMedian(tmp, n);
  float mad = computeMAD(tmp, n, med);
  // scale MAD
  float sigma = 1.4826 * mad;
  float threshold = 3.0 * sigma; // 3-sigma equivalent in robust terms
  // if sigma==0 (all values identical) accept all
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
      // everything is essentially the same
      inCount++;
      if (v < inMin) inMin = v;
      if (v > inMax) inMax = v;
    }
  }
  if (inCount == 0) {
    // fallback to median center +/- small window
    outMin = med;
    outMax = med;
  } else {
    outMin = inMin;
    outMax = inMax;
  }
  free(tmp);
}

// linear map float
float mapFloat(float x, float inMin, float inMax, float outMin, float outMax) {
  if (inMax <= inMin) return outMin;
  float t = (x - inMin) / (inMax - inMin);
  if (t < 0.0) t = 0.0;
  if (t > 1.0) t = 1.0;
  return outMin + t * (outMax - outMin);
}

//helper function to read sensor lux with adjustable addressed I2C pins
// Read lux from a specific sensor by switching I2C pins
float readSensorLux(int sda, int scl) {
  Wire.begin(sda, scl);
  delay(10);  // Small delay for I2C bus to stabilize
  
  // Reinitialize the sensor on the new bus
  if (!veml.begin()) {
    Serial.print("Warning: Sensor not found on SDA=");
    Serial.print(sda);
    Serial.print(" SCL=");
    Serial.println(scl);
    return 0.0;  // Return 0 if sensor not found
  }
  
  // Reconfigure sensor settings (they may reset after begin())
  veml.setGain(VEML7700_GAIN_1);
  veml.setIntegrationTime(VEML7700_IT_100MS);
  
  float lux = veml.readLux();
  return lux;
}

void setup() {
  Serial.begin(115200);

  // Initialize first I2C bus and sensor
  I2C_1.begin(SDA1, SCL1);
  if (!veml1.begin(&I2C_1)) {
    Serial.println("VEML7700 #1 not found");
    while (1);
  }
  veml1.setGain(VEML7700_GAIN_1);
  veml1.setIntegrationTime(VEML7700_IT_100MS);

  // Initialize second I2C bus and sensor
  I2C_2.begin(SDA2, SCL2);
  if (!veml2.begin(&I2C_2)) {
    Serial.println("VEML7700 #2 not found");
    while (1);
  }
  veml2.setGain(VEML7700_GAIN_1);
  veml2.setIntegrationTime(VEML7700_IT_100MS);

  pinMode(LED_PIN, OUTPUT);
  ledcSetup(0, 5000, 8);  // Channel 0, 5kHz, 8-bit PWM
  ledcAttachPin(LED_PIN, 0);

  Serial.println("VEML7700 initialized.");
  lastSample = millis();
}

void loop() {
  unsigned long now = millis();
  if (now - lastSample >= SAMPLE_MS) {
    lastSample = now;
    
    // read raw lux from both sensors simultaneously
    float lux1 = veml1.readLux();
    float lux2 = veml2.readLux();
    float rawLux = (lux1 + lux2) / 2.0;

    //calling filter module 
    float filtered;
    if (activeFilter == 0) filtered = sma.process(rawLux);
    else if (activeFilter == 1) filtered = ema.process(rawLux);
    else filtered = sg.process(rawLux);

    // push filtered into calibration buffer
    calibBuffer.add(filtered);

    // every sample (or we could do this less frequently), recompute robust bounds from last WINDOW_SIZE filtered readings
    float newMin, newMax;
    computeRobustBounds(newMin, newMax);

    // Smoothly blend the current global bounds toward new ones to avoid abrupt jumps
    minLux = (1.0 - BOUNDS_ALPHA) * minLux + BOUNDS_ALPHA * newMin;
    maxLux = (1.0 - BOUNDS_ALPHA) * maxLux + BOUNDS_ALPHA * newMax;

    // Ensure sensible span (avoid degenerate case)
    if (maxLux <= minLux + 1e-3) {
      // expand a tiny amount
      maxLux = minLux + 1.0;
    }

    // map filtered value to PWM 0..255
    float mapped = mapFloat(filtered, minLux, maxLux, 0.0, 255.0);
    int pwm = (int)round(mapped);
    if (pwm < 0) pwm = 0;
    if (pwm > 255) pwm = 255;
    ledcWrite(0, pwm);

    // Debug prints (can be commented out)
    Serial.print("raw: "); Serial.print(rawLux);
    Serial.print(" filt: "); Serial.print(filtered);
    Serial.print(" min: "); Serial.print(minLux);
    Serial.print(" max: "); Serial.print(maxLux);
    Serial.print(" pwm: "); Serial.println(pwm);
  }

  // Other non-blocking tasks can be handled here...
}
