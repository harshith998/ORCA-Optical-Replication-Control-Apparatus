// ESP32 Chamber Configuration File

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

// ---------- Other Settings ----------
#define I2C_FREQUENCY 400000 // 400 kHz Frequency
#define LOOP_DELAY_MS 100         // 100 milliseconds loop delay

// ---------- Filtering & Dynamic Bounds Settings ----------
#define ENABLE_FILTERING 1        // Enable filtering and dynamic bounds (0=disabled, 1=enabled)
#define FILTER_TYPE 1             // 0=none, 1=SMA, 2=EMA, 3=SG (Savitzky-Golay)
#define SMA_WINDOW 11             // SMA window size (odd number recommended)
#define EMA_ALPHA 0.1             // EMA smoothing factor (0.0-1.0, higher=more responsive)
#define SG_WINDOW 11              // Savitzky-Golay window size (odd number)
#define SG_POLY_ORDER 3           // SG polynomial order
#define CALIB_WINDOW_SIZE 600     // Calibration buffer: 5 min @ 100ms = 600 samples
#define BOUNDS_ALPHA 0.05         // Bounds smoothing (0.0-1.0, lower=slower adjustment)
#define MAD_THRESHOLD 3.0         // Outlier threshold (3.0 sigma)