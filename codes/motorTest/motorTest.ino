// Teensy 4.0 -> DM542T basic STEP/DIR test (no library)
// Works with "common-cathode" wiring: PUL-/DIR-/ENA- to GND, drive + pins from Teensy.
//
// Set your DM542T microstep DIP to match PULSES_PER_MOTOR_REV below.
// Example: if DIP says 1600 pulses/rev => use 1600.

#include <Arduino.h>

#if defined(CORE_TEENSY)
  #define WRITE_PIN digitalWriteFast
#else
  #define WRITE_PIN digitalWrite
#endif

// ---- Pins (change if you want) ----
const int STEP_PIN = 2;   // -> PUL+
const int DIR_PIN  = 3;   // -> DIR+
const int EN_PIN   = 4;   // -> ENA+ (optional)

// ---- Your setup parameters ----
const int  PULSES_PER_MOTOR_REV = 1600;  // DM542T "Pulse/rev" DIP setting (common: 400,800,1600,3200,...)
const float GEAR_RATIO = 5.18f;          // from your motor page (~5.18:1)

// Output rev pulses = motor pulses/rev * gearbox ratio
const long PULSES_PER_OUTPUT_REV = (long)(PULSES_PER_MOTOR_REV * GEAR_RATIO + 0.5f);

// Speed control (pulse period in microseconds)
// Example: 1000us period => 1000 pulses/sec
const unsigned int STEP_PERIOD_US = 500;   // adjust: smaller = faster (e.g. 500, 250, 200...)
const unsigned int STEP_HIGH_US   = 5;      // STEP high time (>=2-5us is safe)

// If your EN behavior feels inverted, flip these:
const bool ENABLE_ACTIVE_HIGH = true; // For common-cathode, ENA+ HIGH usually enables

void setEnable(bool en) {
  if (EN_PIN < 0) return;
  if (ENABLE_ACTIVE_HIGH) {
    WRITE_PIN(EN_PIN, en ? HIGH : LOW);
  } else {
    WRITE_PIN(EN_PIN, en ? LOW : HIGH);
  }
}

void stepOnce(unsigned int period_us) {
  // Rising edge is what matters; keep HIGH briefly, then LOW for rest of period
  WRITE_PIN(STEP_PIN, HIGH);
  delayMicroseconds(STEP_HIGH_US);
  WRITE_PIN(STEP_PIN, LOW);

  unsigned int lowTime = (period_us > STEP_HIGH_US) ? (period_us - STEP_HIGH_US) : 1;
  delayMicroseconds(lowTime);
}

void movePulses(long pulses, bool dir, unsigned int period_us) {
  WRITE_PIN(DIR_PIN, dir ? HIGH : LOW);
  delayMicroseconds(10); // small setup time before stepping

  for (long i = 0; i < pulses; i++) {
    stepOnce(period_us);
  }
}

void setup() {
  Serial.begin(115200);

  pinMode(STEP_PIN, OUTPUT);
  pinMode(DIR_PIN, OUTPUT);
  pinMode(EN_PIN, OUTPUT);

  WRITE_PIN(STEP_PIN, LOW);
  WRITE_PIN(DIR_PIN, LOW);

  setEnable(true);  // enable driver (optional)
  delay(200);

  Serial.println("DM542T + Teensy 4.0 step test starting...");
  Serial.print("PULSES_PER_OUTPUT_REV = ");
  Serial.println(PULSES_PER_OUTPUT_REV);
}

void loop() {
  // 1 output shaft revolution forward
  Serial.println("Forward: 2 output rev");
  movePulses(PULSES_PER_OUTPUT_REV, true, STEP_PERIOD_US);
  delay(800);

  // 1 output shaft revolution backward
  Serial.println("Backward: 1 output rev");
  movePulses(PULSES_PER_OUTPUT_REV, false, STEP_PERIOD_US);
  delay(800);
}
