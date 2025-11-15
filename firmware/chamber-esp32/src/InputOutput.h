#ifndef INPUT_OUTPUT_H
#define INPUT_OUTPUT_H

#include <Arduino.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <string>
#include "Config.h"

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

  void readSwitches();    // Update sw1 & sw2
  void readAnalog();      // Update potValue
  void readUART();        // Update inputLux 
};

#endif