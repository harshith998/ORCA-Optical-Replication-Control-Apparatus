#include "InputOutput.h"

InputOutput io;

enum DisplayMode { MODE_ANALOG = 0, MODE_LUX = 1 };

// runtime state
static DisplayMode displayMode = MODE_LUX;
static bool pwmEnabled = false;

void setup() {
  io.begin();  // Initialize all peripherals

  // ensure PWM off at start
  io.setPWM(0);
}

void loop() {
  io.update();  // Update input/output states

  // Read current switches (INPUT_PULLUP: true==HIGH==released, false==LOW==pressed)
  bool sw1 = io.getSwitch1();
  bool sw2 = io.getSwitch2();

  // Swithc controls
  if (sw1) {
    displayMode = MODE_ANALOG;
  }
  else {
    displayMode = MODE_LUX;
  }

  if (sw2) {
    pwmEnabled = false;
  }
  else {
    pwmEnabled = true;
  }

  // Determine the input value (0.0 - 1.0) depending on mode
  float inputNorm = 0.0f;
  int lux = io.getLuxValue();
  float pot = io.getAnalogValue(); // already scaled 0..1 in InputOutput

  if (displayMode == MODE_ANALOG) {
    inputNorm = pot;
  } else {
    // interpret lux as a value out of 10000 (as requested)
    inputNorm = (float)lux / 2750.0f;
    if (inputNorm < 0.0f) inputNorm = 0.0f;
    if (inputNorm > 1.0f) inputNorm = 1.0f;
  }

  // Apply PWM if enabled
  if (pwmEnabled) {
    // scale to configured max PWM value (from Config.h)
    uint32_t duty = (uint32_t)(inputNorm * (float)MAX_PWM_VALUE + 0.5f);
    if (duty > MAX_PWM_VALUE) duty = MAX_PWM_VALUE;
    io.setPWM((float)duty);
  }
  else {
    io.setPWM(0.0);
  }

  // Update LCD display: print mode and value (fit to 16x2)
  LiquidCrystal_I2C lcd = io.getLCD();
  lcd.clear();
  lcd.setCursor(0, 0);
  if (displayMode == MODE_ANALOG) {
    lcd.print("Mode: ANALOG");
  } else {
    lcd.print("Mode: LUX    ");
  }

  lcd.setCursor(0, 1);
  if (displayMode == MODE_ANALOG) {
    // show pot value as fraction
    lcd.print("Pot:");
    lcd.print(pot, 3);
  } else {
    // show raw lux reading and percent of 10k
    lcd.print("Lux:");
    lcd.print(lux);
  }

  // Optional serial log for debugging
  Serial.println(io.toString());

  delay(LOOP_DELAY_MS); // update rate
}