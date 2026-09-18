# Firmware — Teensy 4.0

Location: [`HighPrecisionStepperJuggler-master/Arduino/HighPrecisionStepperJuggler/`](../HighPrecisionStepperJuggler-master/Arduino/HighPrecisionStepperJuggler/)

The Teensy's job is deliberately simple:

- Listen for movement commands on the serial bus
- Generate pulses for the stepper motors, using a sine-profile pulse generator (`SineStepper`) driven
  from a hardware timer interrupt

### Uploading

1. Install the Arduino IDE with **Teensyduino**.
2. Open `HighPrecisionStepperJuggler.ino`, select **Teensy 4.0**, and set **USB Type: Serial**.
3. Upload. The board then listens on USB serial. The `921600` baud is nominal, since Teensy USB
   serial ignores the baud rate.

Connecting to the port does **not** reset a Teensy, and the motors' power-on position is their zero.
Power the machine up with the plate resting in its mechanical dead position.

### Wire protocol

Each line sent to the board holds one or more move batches of six colon-separated numbers, with up
to 100 batches concatenated:

```
PC  → MCU   <marker>:<a0>:<a1>:<a2>:<a3>:<move_time>[:<marker>:...]
            PING
MCU → PC    PONG
```

| Field | Meaning |
|---|---|
| `marker` | `11.0 × batch number`, counting from 1. A batch whose marker does not match is skipped. |
| `a0 … a3` | The four arm angles in **radians**, measured from the **power-on pose**. |
| `move_time` | Seconds. Anything below **0.05 s** is raised to 0.05 s. |

Things the protocol does not do, which catch people out:

- **There is no HOME or STOP command.** Parking and emergency stop are both ordinary moves to the
  origin pose.
- **A malformed line fails silently.** The firmware parses nothing and does nothing, which looks
  exactly like dead motors. If the plate will not move, send `PING` first.
- **A new line cancels the running move.** Every move is a half-cosine that starts from rest, so
  re-sending the same target on every control tick restarts the profile each time and the plate
  crawls. A long move must be sent once and then left alone.
- **It is almost silent by design.** With `VERBOSE_SERIAL_LOGGING 0` the board answers `PING` and
  reports a bad marker, and says nothing else, not even for an accepted move.

### Key constants (`Constants.h`)

| Constant | Value | Why |
|---|---|---|
| `PULSES_PER_REV` | 16576 | 1/16 microstepping × 5.18 gearbox. Must match the DIP switches. |
| `MOVE_DURATION` | 0.05 s | Minimum accepted move time |
| `TIMER_US` / `FREQUENCY_MULTIPLIER` | 10 µs / 1e-5 | Must describe the same tick. A mismatch makes every move slower than requested. |
| Peak step rate | ~25 000 steps/s | One toggle per two 10 µs ticks. This is what limits stroke speed. |
| `MAX_NUM_OF_MOVEBATCHES` | 100 | Batches per line |
| `VERBOSE_SERIAL_LOGGING` | 0 | Set to 1 only while bringing up the link. At control rates it adds latency. |

[`codes/`](../codes/) holds bare STEP/DIR test sketches (`motorTest`, `allmotor`, `fixedmove`, …) for
checking drivers and motors without the full firmware.

Both host applications speak this protocol; neither replaces it.

---

[← Back to the main README](../README.md) · [Hardware](hardware.md) · [Firmware](firmware.md) · [PyQt app](../pyballbalancer/README.md) · [Unity app](unity-app.md) · [Camera & motion](camera-and-motion.md) · [Troubleshooting](troubleshooting.md) · [Repository](repository.md)
