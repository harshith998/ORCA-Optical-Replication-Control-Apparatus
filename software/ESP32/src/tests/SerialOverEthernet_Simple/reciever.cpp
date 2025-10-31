// RECEIVER Arduino
// TX/RX pins connected through ethernet cable from other Arduino

void setup() {
  // Serial to computer (to display received data)
  Serial.begin(9600);
  
  Serial.println("Receiver ready - waiting for data...");
}

void loop() {
  // Check if data is available from the ethernet cable (serial connection)
  if (Serial.available() > 0) {
    // Read and display incoming data
    char c = Serial.read();
    Serial.print(c);
  }
}