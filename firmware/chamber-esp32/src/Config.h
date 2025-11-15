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