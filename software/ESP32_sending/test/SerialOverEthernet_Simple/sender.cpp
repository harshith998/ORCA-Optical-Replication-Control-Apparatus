// SENDER Arduino
// TX/RX pins connected through ethernet cable to other Arduino

void setup() {
  Serial.begin(9600);
  
  Serial.println("Sender ready");
}

void loop() {
  // Send data over the ethernet cable (acting as serial wire)
  Serial.println("Hello from sender!");
  Serial.print("Counter: ");
  Serial.println(millis());
  Serial.println("---");
  
  delay(2000); // Send every 2 seconds
}