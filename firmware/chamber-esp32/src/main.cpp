#include "InputOutput.h"

InputOutput io;

void setup() {
  io.begin();  // Initialize all peripherals
}

void loop() {
  io.update();  // Update input/output states

  // START

  // INSERT PROCESSING CODE HERE

  // END

  // io.toString(); // Optional: print debug info
  delay(LOOP_DELAY_MS); // Adjust update rate as needed
}
