  /*
  HighPrecisionStepperJuggler
  Author: T-Kuhn.
  Sapporo, January, 2020. Released into the public domain.
 */

#include "Constants.h"
#include "SineStepper.h"
#include "SineStepperController.h"
#include "MoveBatch.h"

enum Mode
{
    idle,
    doingControlledMovements,
    error
};

volatile Mode currentMode = idle;
char inputBuffer[INPUT_SIZE + 1];

SineStepper sineStepper1(STEPPER1_STEP_PIN, STEPPER1_DIR_PIN, /*id:*/ 0);
SineStepper sineStepper2(STEPPER2_STEP_PIN, STEPPER2_DIR_PIN, /*id:*/ 1);
SineStepper sineStepper3(STEPPER3_STEP_PIN, STEPPER3_DIR_PIN, /*id:*/ 2);
SineStepper sineStepper4(STEPPER4_STEP_PIN, STEPPER4_DIR_PIN, /*id:*/ 3);

SineStepperController sineStepperController(/*endlessRepeat:*/ false);
IntervalTimer myTimer;

void onTimer()
{
    digitalWrite(EXECUTING_ISR_CODE, HIGH);

    switch (currentMode)
    {
    case idle:
        break;
    case doingControlledMovements:
        sineStepperController.update();
        break;
    default:
        break;
    }
    digitalWrite(EXECUTING_ISR_CODE, LOW);
}

void setup()
{
    inputBuffer[0] = '\0';
    Serial.begin(921600);
    Serial.setTimeout(1);
    myTimer.begin(onTimer, TIMER_US);

    pinMode(EXECUTING_ISR_CODE, OUTPUT);

    sineStepperController.attach(&sineStepper1);
    sineStepperController.attach(&sineStepper2);
    sineStepperController.attach(&sineStepper3);
    sineStepperController.attach(&sineStepper4);
}

void loop()
{

    if (Serial.available() > 0)
    {
        char inputChar = Serial.read();
        static int s_len;
        if (s_len >= INPUT_SIZE)
        {
            // We have received already the maximum number of characters
            // Ignore all new input until line termination occurs
        }
        else if (inputChar != '\n' && inputChar != '\r')
        {
            inputBuffer[s_len++] = inputChar;
        }
        else
        {
            // We have received a LF or CR character
            inputBuffer[s_len] = 0;

            // Liveness check. Handled before strtok(), which destroys the buffer.
            if (strcmp(inputBuffer, "PING") == 0)
            {
                Serial.println("PONG");
                memset(inputBuffer, 0, sizeof(inputBuffer));
                s_len = 0;
                return;
            }

#if VERBOSE_SERIAL_LOGGING
            Serial.print("RECEIVED MSG: ");
            Serial.println(inputBuffer);
#endif

            currentMode = idle;
            // Discard batches left over from the previous command so they can't
            // execute stale positions after the new ones finish.
            sineStepperController.clearAllMoveBatches();
            int index = 0;
            double instructionData[MAX_NUM_OF_MOVEBATCHES * 6];
            for (int i = 0; i < MAX_NUM_OF_MOVEBATCHES * 6; i++)
            {
                instructionData[i] = 0;
            }

            // Read each command
            char *command = strtok(inputBuffer, ":");
            while (command != 0)
            {
                instructionData[index] = atof(command);

                command = strtok(0, ":");
                index++;
            }

            int numOfMoveBatches = index / 6;

#if VERBOSE_SERIAL_LOGGING
            Serial.print("Parsed tokens (count=");
            Serial.print(index);
            Serial.print("): ");
            for (int t = 0; t < index; t++)
            {
                Serial.print(instructionData[t], 5);
                if (t < index - 1) Serial.print(" |");
            }
            Serial.println();

            Serial.print("Num of move batches: ");
            Serial.println(numOfMoveBatches);
#endif

            for (int i = 0; i < numOfMoveBatches; i++)
            {
                int offset = i * 6;
                MoveBatch *mb = &sineStepperController.moveBatches[i];
                
#if VERBOSE_SERIAL_LOGGING
                Serial.print("Batch "); Serial.print(i); Serial.print(" marker value: "); Serial.println(instructionData[offset], 5);
#endif

                if (instructionData[offset] > ((i + 1) * 11.0) - 0.1 && instructionData[offset] < ((i + 1) * 11) + 0.1)
                {
                    int32_t p0 = (int32_t)(PULSES_PER_REV * (instructionData[offset + 1] / (M_PI * 2)));
                    int32_t p1 = (int32_t)(PULSES_PER_REV * (instructionData[offset + 2] / (M_PI * 2)));
                    int32_t p2 = (int32_t)(PULSES_PER_REV * (instructionData[offset + 3] / (M_PI * 2)));
                    int32_t p3 = (int32_t)(PULSES_PER_REV * (instructionData[offset + 4] / (M_PI * 2)));

                    mb->addMove(/*id:*/ 0, /*pos:*/ p0);
                    mb->addMove(/*id:*/ 1, /*pos:*/ p1);
                    mb->addMove(/*id:*/ 2, /*pos:*/ p2);
                    mb->addMove(/*id:*/ 3, /*pos:*/ p3);

                    float requestedMoveDuration = instructionData[offset + 5];
                    if (requestedMoveDuration < MOVE_DURATION)
                    {
                        requestedMoveDuration = MOVE_DURATION;
                    }
                    mb->moveDuration = requestedMoveDuration;

#if VERBOSE_SERIAL_LOGGING
                    Serial.println("Marker matches expected value.");
                    Serial.print("Motor0 pulses: "); Serial.println(p0);
                    Serial.print("Motor1 pulses: "); Serial.println(p1);
                    Serial.print("Motor2 pulses: "); Serial.println(p2);
                    Serial.print("Motor3 pulses: "); Serial.println(p3);
                    Serial.print("Move duration: "); Serial.println(mb->moveDuration, 5);
#endif
                }
                else
                {
                    Serial.println("Marker did NOT match expected value - skipping batch.");
                }
            }

            sineStepperController.resetMoveBatchExecution();
            currentMode = doingControlledMovements;

            memset(inputBuffer, 0, sizeof(inputBuffer));
            s_len = 0;
        }
    }
}
