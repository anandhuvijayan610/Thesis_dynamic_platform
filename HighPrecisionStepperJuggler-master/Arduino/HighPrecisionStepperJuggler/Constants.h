/*
  Constants
  Author:
  */

#ifndef Constants_h
#define Constants_h
#include "Arduino.h"

#define STEPPER1_DIR_PIN 5
#define STEPPER1_STEP_PIN 6
#define STEPPER2_DIR_PIN 1
#define STEPPER2_STEP_PIN 2
#define STEPPER3_DIR_PIN 3
#define STEPPER3_STEP_PIN 4
#define STEPPER4_DIR_PIN 7
#define STEPPER4_STEP_PIN 8

#define NAN_ALERT_LED 25
#define EXECUTING_ISR_CODE 13

// Gear ratio: 1:5.18
// Base motor: 200 steps / rev (full step mode)

// With gear and microstepping, effective steps per revolution are:
//   full step:   200 * 1 * 5.18 = 1036
//   1/2 step:    200 * 2 * 5.18 = 2072
//   1/4 step:    200 * 4 * 5.18 = 4144
//   1/8 step:    200 * 8 * 5.18 = 8288
//   1/16 step:   200 * 16 * 5.18 = 16576
//
// This is the value currently used for the Arduino pulse scaling.
// 16576 pulses correspond to 1 full revolution of the output shaft.
// 500 pulses therefore correspond to about 0.0302 rev, or about 10.9 degrees.

#define PULSES_TO_MOVE 500 // 4000 * 16576 / 132608, keeps the same physical movement after scaling to 16576 pulses/rev
#define PULSES_PER_REV 16576 // 200 * 16 * 5.18 (gear ratio 5.18:1)
//#define MOVE_DURATION 1.0f
//#define PAUSE_DURATION 0.2f
// MOVE_DURATION is the minimum allowed move duration (sanity floor for incoming
// instructions). Unity sends 0.1s moves during balancing, so this must stay below that.
#define MOVE_DURATION 0.05f
#define PAUSE_DURATION 0.5f

//#define FREQUENCY_MULTIPLIER 0.000002f
//#define TIMER_US 2
// A 2 us interrupt was too aggressive for the sine-stepper ISR on the Teensy and could cause missed pulses.
// FREQUENCY_MULTIPLIER must equal TIMER_US expressed in seconds, otherwise moves take
// longer than the requested moveDuration. 10 us gives 5x more ISR headroom than 2 us
// while still allowing peak step rates of ~25k steps/s (one toggle per 2 ticks).
#define FREQUENCY_MULTIPLIER 0.00001f
#define TIMER_US 10

// Set to 1 to echo every received instruction, its parsed tokens and the per-motor pulse
// counts back over serial. Invaluable while bringing the link up, but during balancing Unity
// sends ~7 instructions/s and each one produces ~10 reply lines, which Unity then Debug.Logs -
// enough serial traffic and editor-console churn to add real latency and jitter to a control
// loop that only runs at 6.7Hz to begin with. PING still answers with PONG when this is 0.
#define VERBOSE_SERIAL_LOGGING 0

// NOTE: SineStepper and MoveBatch ids must be lower then MAX_NUM_OF_STEPPERS
#define MAX_NUM_OF_STEPPERS 10
#define MAX_NUM_OF_MOVEBATCHES 100

// Max input size for the list of incoming instructions
#define INPUT_SIZE 5120

#endif
