// Define Pins for 4 Drivers
const int stepPins[] = {2, 4, 6, 8};
const int dirPins[]  = {3, 5, 7, 9};

void setup() {
  // Initialize all pins as outputs
  for (int i = 0; i < 4; i++) {
    pinMode(stepPins[i], OUTPUT);
    pinMode(dirPins[i], OUTPUT);
    
    // Set initial direction (HIGH = Clockwise, LOW = Counter-Clockwise)
    digitalWrite(dirPins[i], HIGH); 
  }
}

void loop() {
  // Move Forward 1600 steps
  digitalWriteAllDirs(HIGH);
  runMotors(1600);
  
  delay(1000); // Wait 1 second

  // Move Backward 1600 steps
  digitalWriteAllDirs(LOW);
  runMotors(1600);

  delay(1000); // Wait 1 second
}

// Helper function to pulse all step pins at once
void runMotors(int steps) {
  for (int i = 0; i < steps; i++) {
    for (int p = 0; p < 4; p++) digitalWrite(stepPins[p], HIGH);
    delayMicroseconds(400); // Speed control (lower = faster)
    for (int p = 0; p < 4; p++) digitalWrite(stepPins[p], LOW);
    delayMicroseconds(400);
  }
}

// Helper function to set all directions
void digitalWriteAllDirs(int state) {
  for (int i = 0; i < 4; i++) {
    digitalWrite(dirPins[i], state);
  }
}
