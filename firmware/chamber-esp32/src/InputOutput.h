#ifndef INPUT_OUTPUT_H
#define INPUT_OUTPUT_H

#include <Arduino.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <string>
#include <cmath>
#include "Config.h"

// ===== Circular Buffer for Calibration Data =====
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

// ===== Filter Base Class =====
struct Filter {
  virtual float process(float value) = 0;
  virtual ~Filter() {}
};

// ===== Simple Moving Average Filter =====
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
    for (int i = 0; i < N; i++) window[i] = 0.0;
  }

  ~SMAFilter() { free(window); }

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

// ===== Exponential Moving Average Filter =====
struct EMAFilter : public Filter {
  float alpha;
  bool initialized;
  float state;

  EMAFilter(float a = 0.1) {
    alpha = a;
    initialized = false;
    state = 0.0;
  }

  ~EMAFilter() {}

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

// ===== Savitzky-Golay Filter =====
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
    for (int i = 0; i < window; i++) { buffer[i] = 0.0; coeffs[i] = 0.0; }
    computeCoefficients();
  }

  ~SGFilter() { free(coeffs); free(buffer); }

  bool invertMatrix(double *mat, double *inv, int n) {
    double *aug = (double*)malloc(sizeof(double) * n * 2 * n);
    if (!aug) return false;

    for (int r = 0; r < n; r++) {
      for (int c = 0; c < n; c++) aug[r*(2*n)+c] = mat[r*n + c];
      for (int c = 0; c < n; c++) aug[r*(2*n)+n + c] = (r==c) ? 1.0 : 0.0;
    }

    for (int col = 0; col < n; ++col) {
      int pivot = col;
      double maxval = fabs(aug[pivot*(2*n) + col]);
      for (int r = col+1; r < n; ++r) {
        double v = fabs(aug[r*(2*n) + col]);
        if (v > maxval) { maxval = v; pivot = r; }
      }
      if (maxval < 1e-12) { free(aug); return false; }

      if (pivot != col) {
        for (int c = 0; c < 2*n; c++) {
          double tmp = aug[col*(2*n)+c];
          aug[col*(2*n)+c] = aug[pivot*(2*n)+c];
          aug[pivot*(2*n)+c] = tmp;
        }
      }

      double pv = aug[col*(2*n) + col];
      for (int c = 0; c < 2*n; c++) aug[col*(2*n)+c] /= pv;

      for (int r = 0; r < n; r++) {
        if (r==col) continue;
        double factor = aug[r*(2*n) + col];
        if (fabs(factor) < 1e-15) continue;
        for (int c = 0; c < 2*n; c++) {
          aug[r*(2*n)+c] -= factor * aug[col*(2*n)+c];
        }
      }
    }

    for (int r = 0; r < n; r++) {
      for (int c = 0; c < n; c++) {
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

    for (int r = 0; r < rows; ++r) {
      int j = r - half;
      double val = 1.0;
      for (int p = 0; p < cols; ++p) {
        A[r*cols + p] = val;
        val *= (double)j;
      }
    }

    double *ATA = (double*)malloc(sizeof(double)*cols*cols);
    for (int i = 0; i < cols*cols; i++) ATA[i] = 0.0;
    for (int i = 0; i < cols; i++) {
      for (int j = 0; j < cols; j++) {
        double s = 0.0;
        for (int r = 0; r < rows; r++) s += A[r*cols + i] * A[r*cols + j];
        ATA[i*cols + j] = s;
      }
    }

    double *invATA = (double*)malloc(sizeof(double)*cols*cols);
    bool ok = invertMatrix(ATA, invATA, cols);

    if (!ok) {
      float avg = 1.0 / window;
      for (int i = 0; i < window; i++) coeffs[i] = avg;
      free(A); free(ATA); free(invATA);
      return;
    }

    double *AT = (double*)malloc(sizeof(double)*cols*rows);
    for (int i = 0; i < cols; i++) {
      for (int r = 0; r < rows; r++) AT[i*rows + r] = A[r*cols + i];
    }

    double *B = (double*)malloc(sizeof(double)*cols*rows);
    for (int i = 0; i < cols; i++) {
      for (int j = 0; j < rows; j++) {
        double s = 0.0;
        for (int k = 0; k < cols; k++) s += invATA[i*cols + k] * AT[k*rows + j];
        B[i*rows + j] = s;
      }
    }

    for (int j = 0; j < rows; j++) coeffs[j] = (float)B[0*rows + j];

    free(A); free(ATA); free(invATA); free(AT); free(B);
  }

  float process(float value) override {
    buffer[pos] = value;
    pos = (pos + 1) % window;
    if (filled < window) filled++;

    if (filled < window) {
      float s = 0.0;
      int n = filled;
      for (int i = 0; i < n; i++) s += buffer[i];
      return s / n;
    }

    float sum = 0.0;
    int start = pos;
    for (int i = 0; i < window; i++) {
      int idx = (start + i) % window;
      sum += coeffs[i] * buffer[idx];
    }
    return sum;
  }
};

class InputOutput {
public:
  InputOutput();
  void begin();             // Setup the IO components
  void update();            // Updates input variables
  bool getSwitch1();        // Get sw1 state {HIGH, LOW}
  bool getSwitch2();        // Get sw2 state {HIGH, LOW}
  float getAnalogValue();   // Get potValue [0,1]
  int getLuxValue();        // Get luxValue [0,MAX)
  LiquidCrystal_I2C getLCD();    // Get lcd object
  void setPWM(float pwmValue);   // Set PWM duty cycle [0,1]
  String toString();        // Return string representation

private:
  LiquidCrystal_I2C lcd;  // Chamber LCD object
  bool sw1, sw2;          // Chamber switch 1 & switch 2
  float potValue;         // Scaled potValue [0, 1]
  int luxValue;           // raw luxValue [0,MAX)

  // Filtering & Dynamic Bounds (only compiled if ENABLE_FILTERING == 1)
#if ENABLE_FILTERING
  Filter *activeFilter;           // Pointer to active filter
  CircularBuffer calibBuffer;     // Buffer for 5-min history
  float minLux;                   // Dynamic minimum bound
  float maxLux;                   // Dynamic maximum bound
  unsigned long lastBoundsUpdate; // Timing for bounds refresh

  // Helper methods for filtering
  float applyFilter(float rawValue);      // Apply filter to raw lux
  void updateDynamicBounds();             // Update bounds from history
  static int cmpFloat(const void *a, const void *b); // Comparator for qsort
  float computeMedian(float *arr, int n);    // Compute median
  float computeMAD(float *arr, int n, float median); // Median absolute deviation
  void computeRobustBounds(float &outMin, float &outMax); // Robust outlier filtering
#endif

  void readSwitches();    // Update sw1 & sw2
  void readAnalog();      // Update potValue
  void readUART();        // Update inputLux
};

#endif