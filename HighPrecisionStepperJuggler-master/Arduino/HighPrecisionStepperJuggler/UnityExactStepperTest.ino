/*
  UnityExactStepperTest
  This sketch receives the same Unity serial command format and executes stepper moves
  using a simple direct step/dir pulse generator.

  Expected input format from Unity:
    marker:rot0:rot1:rot2:rot3:duration\n
  Example:
    11.00000:0.65453:0.65795:0.65898:0.65350:2.00000\n
  It mimics the Unity message creation logic and converts radians to pulses
  using the same PULSES_PER_REV constant from the Arduino firmware.
*/

#include <Arduino.h>

#define STEPPER1_DIR_PIN 5
#define STEPPER1_STEP_PIN 6
#define STEPPER2_DIR_PIN 1
#define STEPPER2_STEP_PIN 2
#define STEPPER3_DIR_PIN 3
#define STEPPER3_STEP_PIN 4
#define STEPPER4_DIR_PIN 7
#define STEPPER4_STEP_PIN 8

#define BAUD_RATE 921600
#define PULSES_PER_REV 16576.0f
#define INPUT_BUFFER_SIZE 128
#define MIN_MOVE_DURATION_SECONDS 0.05f

const char kHardcodedUnityCommand[] = "11.00000:0.65453:0.65795:0.65898:0.65350:2.00000";

char inputBuffer[INPUT_BUFFER_SIZE];
size_t inputIndex = 0;

long radiansToPulses(float radians)
{
  return (long)round(PULSES_PER_REV * (radians / (2.0f * PI)));
}

void setup()
{
  Serial.begin(BAUD_RATE);
  while (!Serial) { }

  pinMode(STEPPER1_DIR_PIN, OUTPUT);
  pinMode(STEPPER1_STEP_PIN, OUTPUT);
  pinMode(STEPPER2_DIR_PIN, OUTPUT);
  pinMode(STEPPER2_STEP_PIN, OUTPUT);
  pinMode(STEPPER3_DIR_PIN, OUTPUT);
  pinMode(STEPPER3_STEP_PIN, OUTPUT);
  pinMode(STEPPER4_DIR_PIN, OUTPUT);
  pinMode(STEPPER4_STEP_PIN, OUTPUT);

  digitalWrite(STEPPER1_STEP_PIN, LOW);
  digitalWrite(STEPPER2_STEP_PIN, LOW);
  digitalWrite(STEPPER3_STEP_PIN, LOW);
  digitalWrite(STEPPER4_STEP_PIN, LOW);

  Serial.println("UnityExactStepperTest ready.");
}

void sendDebug(const char *message)
{
  Serial.println(message);
}

void moveSteppers(long targetPulses[4], float durationSeconds)
{
  bool active[4];
  long remaining[4];
  int dirPins[4] = {STEPPER1_DIR_PIN, STEPPER2_DIR_PIN, STEPPER3_DIR_PIN, STEPPER4_DIR_PIN};
  int stepPins[4] = {STEPPER1_STEP_PIN, STEPPER2_STEP_PIN, STEPPER3_STEP_PIN, STEPPER4_STEP_PIN};

  long maxSteps = 0;
  for (int i = 0; i < 4; i++)
  {
    active[i] = (targetPulses[i] != 0);
    remaining[i] = abs(targetPulses[i]);
    if (targetPulses[i] > 0)
    {
      digitalWrite(dirPins[i], LOW);
    }
    else
    {
      digitalWrite(dirPins[i], HIGH);
    }
    if (remaining[i] > maxSteps)
    {
      maxSteps = remaining[i];
    }
  }

  if (maxSteps == 0)
  {
    Serial.println("No motor pulses requested.");
    return;
  }

  if (durationSeconds < MIN_MOVE_DURATION_SECONDS)
  {
    durationSeconds = MIN_MOVE_DURATION_SECONDS;
  }

  unsigned long totalMicros = (unsigned long)(durationSeconds * 1000000.0f);
  unsigned long stepIntervalMicros = totalMicros / maxSteps;
  if (stepIntervalMicros < 1000UL)
  {
    stepIntervalMicros = 1000UL;
  }
  unsigned long halfIntervalMicros = stepIntervalMicros / 2;

  Serial.print("Executing move: ");
  Serial.print(maxSteps);
  Serial.print(" pulses, duration ");
  Serial.print(durationSeconds, 5);
  Serial.println(" s");

  for (long step = 0; step < maxSteps; step++)
  {
    unsigned long startMicros = micros();
    for (int i = 0; i < 4; i++)
    {
      if (active[i] && remaining[i] > 0)
      {
        digitalWrite(stepPins[i], HIGH);
      }
    }
    delayMicroseconds(halfIntervalMicros);
    for (int i = 0; i < 4; i++)
    {
      if (active[i] && remaining[i] > 0)
      {
        digitalWrite(stepPins[i], LOW);
        remaining[i]--;
      }
    }
    unsigned long elapsed = micros() - startMicros;
    if (elapsed < stepIntervalMicros)
    {
      delayMicroseconds(stepIntervalMicros - elapsed);
    }
  }

  Serial.println("Move complete.");
}

void parseAndExecute(const char *line)
{
  Serial.print("Received: ");
  Serial.println(line);

  char buffer[INPUT_BUFFER_SIZE];
  strncpy(buffer, line, INPUT_BUFFER_SIZE - 1);
  buffer[INPUT_BUFFER_SIZE - 1] = '\0';

  float tokens[6] = {0};
  int tokenCount = 0;
  char *token = strtok(buffer, ":");
  while (token != NULL && tokenCount < 6)
  {
    tokens[tokenCount++] = atof(token);
    token = strtok(NULL, ":");
  }

  if (tokenCount != 6)
  {
    Serial.print("Expected 6 tokens but got ");
    Serial.println(tokenCount);
    return;
  }

  long pulses[4];
  for (int i = 0; i < 4; i++)
  {
    pulses[i] = radiansToPulses(tokens[i + 1]);
    Serial.print("Motor");
    Serial.print(i);
    Serial.print(" pulses: ");
    Serial.println(pulses[i]);
  }

  float durationSeconds = tokens[5];
  moveSteppers(pulses, durationSeconds);
}

void loop()
{
  while (Serial.available() > 0)
  {
    char c = Serial.read();
    if (c == '\r')
    {
      continue;
    }
    if (c == '\n')
    {
      if (inputIndex > 0)
      {
        inputBuffer[inputIndex] = '\0';
        parseAndExecute(inputBuffer);
        inputIndex = 0;
      }
    }
    else if (inputIndex < INPUT_BUFFER_SIZE - 1)
    {
      inputBuffer[inputIndex++] = c;
    }
  }
}
