int stepPin = 2; 
int dirPin = 3;

void setup() {
  pinMode(stepPin, OUTPUT);
  pinMode(dirPin, OUTPUT);
}

void loop() {
  // 1. Pick a direction
  digitalWrite(dirPin, HIGH); 

  // 2. Count out the steps like a teacher counting jumping jacks
  for(int x = 0; x < 8000; x++) // 8000 pulses inside motor to produce 1 full circle in the shaft
  {
    digitalWrite(stepPin, HIGH);  // Pulse ON
    delayMicroseconds(500);       // Wait a tiny bit
    digitalWrite(stepPin, LOW);   // Pulse OFF
    delayMicroseconds(500);       // Wait a tiny bit
  }

  // 3. Take a nap for 2 seconds before doing it again
  delay(2000); 
}
