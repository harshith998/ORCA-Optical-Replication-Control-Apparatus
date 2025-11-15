#ifndef INPUT_OUTPUT_H
#define INPUT_OUTPUT_H

#include <Arduino.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include "Config.h"

class InputOutput {
public:
  InputOutput();
  void begin();
  void update();
  bool getSwitch1();
  bool getSwitch2();
  int  getAnalogValue();
  int  getLuxValue();
  int  computePWM();

private:
  LiquidCrystal_I2C lcd;
  bool sw1, sw2;
  int potValue;
  int inputLux;
  int pwmValue;

  void readSwitches();
  void readAnalog();
  void readUART();
  void updatePWM();
  void printSerialSummary();
  void updateLCD();
};

#endif
