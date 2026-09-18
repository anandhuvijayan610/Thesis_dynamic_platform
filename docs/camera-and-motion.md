# Camera field of view, and the motion physics

## The camera: why field of view governs everything

This is the constraint that shaped most design decisions on this rig, for both hosts.

The camera looks up through the transparent plate. Its distance to the plate is **67.95 mm with the
plate at the mechanical dead position**, and it grows with plate height, so **raising the plate
widens the view**. The ball is large for how close the camera is: at 50 mm above the working origin
its image is ~175 px across in a 480 px axis.

| Height above working origin | Camera distance | mm per pixel | Ball diameter (px) | Room for the ball's centre before it clips (480 px axis) |
|---|---|---|---|---|
| 0 mm | 88 mm | 0.15 | ~271 | ±15 mm |
| 35 mm | 123 mm | 0.20 | ~196 | ±29 mm |
| 50 mm | 138 mm | 0.23 | ~175 | ±35 mm |
| 70 mm | 158 mm | 0.26 | ~153 | ±44 mm |

*(The working origin is 20 mm above the dead position. Figures use the 60.41° FOV over 640 px and a
20 mm ball radius.)*

Consequences:

- **Detection precision is not the limit; the field of view is.** A pixel is a quarter of a
  millimetre, while ball errors are tens of millimetres.
- **A clipped ball is measured wrongly without any error being raised.** When the ball crosses the
  frame edge the blob becomes a crescent, and its centre is reported **pulled toward the middle** —
  by up to ~5.6 mm when a third of the disc is cut off.
- **Keep targets and juggling well inside the window.** That is why both hosts' juggling modes stop
  throwing and re-centre past 30 mm. Targets at ±40 mm (as in the original Full Juggling Demo)
  leave the ball clipped a large fraction of the time.
- **Exposure matters more than the colour gate.** An over-exposed ball clips to white, loses its
  colour and is detected as a crescent. Fix exposure before touching thresholds.

---

## Motion physics worth knowing

- **Half-cosine moves.** Peak plate acceleration is `π²·A / (2·T²)` for stroke `A` over time `T`.
- **The ball separates part way up, not at the top.** It leaves the plate when the plate's
  deceleration exceeds 1 g, and its exit speed is `v_peak · √(1 − (g/a_peak)²)`.
- **Stroke speed is capped by the step-rate ceiling.** Plate speed is `π·A / 2T`, and the ~25 kHz
  pulse ceiling forces `T` to grow with `A`. Feasible strokes therefore all top out around the same
  exit speed. A shorter, faster stroke buys peak **acceleration**, which is what decides separation.
- **Tilt only moves a ball that is on the plate.** While the ball is airborne tilt does nothing, so
  the contact phases of a juggle are where the steering happens.
- **A juggling cycle's timing sets the control rate.** Unity's `MachineController` adds a 50 ms
  margin after every batch it sends, which caps how often a correction can land.

---

## Motion physics worth knowing

- **Half-cosine moves.** Peak plate acceleration is `π²·A / (2·T²)` for stroke `A` over time `T`.
- **The ball separates part way up, not at the top.** It leaves the plate when the plate's
  deceleration exceeds 1 g, and its exit speed is `v_peak · √(1 − (g/a_peak)²)`.
- **Stroke speed is capped by the step-rate ceiling.** Plate speed is `π·A / 2T`, and the ~25 kHz
  pulse ceiling forces `T` to grow with `A`. Feasible strokes therefore all top out around the same
  exit speed. A shorter, faster stroke buys peak **acceleration**, which is what decides separation.
- **Tilt only moves a ball that is on the plate.** While the ball is airborne tilt does nothing, so
  the contact phases of a juggle are where the steering happens.
- **A juggling cycle's timing sets the control rate.** Unity's `MachineController` adds a 50 ms
  margin after every batch it sends, which caps how often a correction can land.

---

[← Back to the main README](../README.md) · [Hardware](hardware.md) · [Firmware](firmware.md) · [PyQt app](../pyballbalancer/README.md) · [Unity app](unity-app.md) · [Camera & motion](camera-and-motion.md) · [Troubleshooting](troubleshooting.md) · [Repository](repository.md)
