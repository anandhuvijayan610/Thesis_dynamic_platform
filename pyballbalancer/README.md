# Ball Balancer — PyQt5 control application

*One of the two host applications in this project. See the
[main README](../README.md) for the machine as a whole, and
[docs/hardware.md](../docs/hardware.md) / [docs/firmware.md](../docs/firmware.md) for what this
talks to. The Unity host is separate: **do not copy tuning between them**.*

A replacement for the Unity host application: camera capture, ball detection,
tilt control, serial link to the microcontroller, and live tuning of every
parameter without restarting.

```
pip install -r requirements.txt
python main.py
```

## Modules

| file | responsibility |
|---|---|
| `params.py` | every tunable value, declared once in `SPECS`; the GUI is generated from it |
| `camera.py` | `CameraWorker` — capture thread, applies UVC controls, runs detection |
| `vision.py` | two interchangeable detectors, both returning centre-frame coordinates |
| `control.py` | velocity estimation, PID, mirror-law tilt, the fixed-rate `ControlLoop` |
| `serial_io.py` | `SerialWorker` — owns the port, coalesces writes, applies the level trim, parses telemetry |
| `machine.py` | kinematics: plate pose → four arm angles → the firmware's wire format |
| `machine_panel.py` | the Machine tab: manual moves, levelling at the working height, bring-up tests |
| `modes.py` | the session modes and juggling supervision; owns height, move time and cadence |
| `optics.py` | camera window and throw physics, validated against the rig |
| `datalog.py` | buffered CSV recorder |
| `widgets.py` | parameter editors and the video view |
| `gui.py` | `MainWindow` — assembles panels, owns the workers, routes signals |
| `main.py` | entry point |

Threads: capture, control and serial each own one. The GUI thread only paints.
Anything crossing a thread boundary goes through a Qt signal, except the
parameter store, which is guarded by a lock because both worker threads read it.

## The firmware protocol

The Teensy runs the SineStepper sketch, and its protocol is not a command
language. Each line is colon-separated doubles, six per move batch, with up to
100 batches concatenated:

```
PC  -> MCU   <marker>:<a0>:<a1>:<a2>:<a3>:<move_time>
             PING
MCU -> PC    PONG
```

`marker` is `11.0 x batch_number`, counting from one, and a batch whose marker
does not match is skipped. `a0..a3` are the four arm angles in **radians**, as
a **difference from the origin pose**, because the firmware treats its power-on
position as zero. `move_time` is in seconds and is clamped up to a 0.05 s floor.

There is no `HOME` and no `STOP`. Levelling and the emergency stop are both a
move to the origin pose — the safe state has to be commanded, not requested.
`PING` is the exception: it is answered with `PONG` before the line reaches the
parser, so it is the only liveness check available.

`machine.py` turns a plate pose — height in metres, two tilts in degrees — into
those four angles, and `machine.serialize()` builds the line. Nothing else in
the application knows the wire format.

**A malformed line fails silently.** The firmware's `strtok`/`atof` parse yields
zero batches and it does nothing at all, so a protocol mismatch is
indistinguishable from dead motors. If the plate will not move, PING first.

**Pose commands are coalesced.** If the control loop outruns the port, only the
newest pose is sent. A stale tilt is worse than none, and a growing backlog
would show up as the plate lagging the ball by a variable amount.

## If the plate looks tilted

The motors hold whatever pose they were last given. Anything that stops without
tidying up — a diagnostic script that ends mid-sequence, a window that is killed
rather than closed — leaves the plate at the last tilt the control loop asked
for. It looks exactly like the levelling trim having drifted, and it is not.

```
python park.py
```

That commands the calibrated level origin and prints the line it sent beside the
line an untrimmed plate would get. The trim is working if the four arm angles
differ from each other; if all four are identical, the trim has been lost.
**Close the window rather than killing it** — `closeEvent` parks the plate on
the way out, and a force-kill skips it.

## Settled calibration

These are on this machine, found by adjustment until the ball sits still in the
middle of the plate and does not roll:

```
arm pairing     0+2 / 1+3                 motors confirmed opposite by eye
working origin  20 mm above the mechanical dead position
level trim      X -0.40, Y -0.40 degrees, levelled at 35 mm (mac_trim_height)
axis mapping    swap/invertX/invertY all off
gains           kp 0.02  ki 0.10  kd 0.04 per axis,  integral clamp 20,
                scaled with ball radius (reference radius 111 px)
limits          max tilt 3 deg, max tilt rate 25 deg/s, command rate 100 Hz
camera          exposure -8, gain 120
detection       H 0..20, S>=150, V>=15, kernel 7, min fill 0.80, min circularity 0.30
```

The trim and gains have been re-found more than once as the rig changed: an
earlier set (trim X -1.30 / Y +0.35, kp 0.05 / kd 0.07) predates levelling at
the working height and is superseded. The values above are the shipped defaults
in `params.py`.

Two things about the trim are easy to get wrong. It is **per pairing** --
changing which motor each tilt drives invalidates it -- and it is **per
height**: these differ by about 1.5 degrees from the values a spirit level
gives at the origin, because the linkage carries a residual slope between the
origin and the 40 mm the controller runs at. Levelling at the origin is not
enough; the definition that matters is where the ball stays.

The integral term is what removes that slope, and `pid_i_clamp` is the part
that makes it possible: it bounds the tilt the integral may ask for at
`Ki x clamp`. At the old clamp of 2.0 that ceiling was 0.2 degrees with
Ki=0.1, far short of the degree or so a real slope needs, so raising Ki alone
achieved nothing. Simulated against a 1.4 degree slope, ki=0 leaves 28 mm of
standing offset and ki=0.1 with clamp 20 leaves none, halving the peak
excursion as well. Ki=0.8 is unstable, so there is plenty of margin.

**Adjusting until the ball stays beats measuring the slope and correcting it.**
Measuring it from the ball's drift open-loop was not reproducible here: the
same trim read `(+334, +748)` on one run and `(-677, -710)` on the next, sign
flipped on both axes, because the ball is placed by hand and is still moving
when the reading starts. Fitting acceleration instead of velocity removes the
dependence on that initial speed and is exact without noise, but over the short
arc the ball survives it is far too noisy to act on.

## Levelling the plate

The plate does not sit level when all four arms are at their origin — arm
length tolerances and how the joints seated during assembly leave a standing
tilt, on this rig along the X pair. `mac_trim_x` and `mac_trim_y` cancel it.

Set them from the Machine tab, with a spirit level on the plate: the nudge
buttons move the trim and immediately re-send the origin pose, so the plate is
adjusted by eye. Do X first — tilting one pair changes how level the other
looks. The offset is then added to *every* commanded tilt, the control loop's
included, so a level plate here means the controller's zero is the real zero
rather than a standing bias it has to fight.

It is applied in exactly one place: `SerialWorker`, the funnel every wire-bound
pose passes through. Several call sites build poses — the Machine panel, the
mode runner, the emergency stop — and applying it at each would eventually miss
one or double it somewhere.

**It is deliberately not folded into `ORIGIN_ANGLES`.** `serialize()` subtracts
that constant from every target, so a trim added there too would cancel itself
out and the plate would never move. The Unity host documents the same trap for
its own origin offset.

**Level where the loop works, not at the origin.** The linkage carries a
residual slope that changes along its travel, so the trim is a property of the
*height* as much as of the machine -- here the two differ by about 1.5 degrees
between the origin and the working height. The nudge buttons therefore send the
plate to `mac_trim_height` (35 mm above the working origin by default) and
adjust it there, rather than at the origin. A spirit level gets you close; the
definition that matters is that the ball stays put at that height. See
**Settled calibration** above for the shipped values.

Measured on the rig, the origin pose at several trims:

```
trim X      a0       a1       a2       a3
+0.00    0.11941  0.11941  0.11941  0.11941
+0.50    0.13462  0.10415  0.11941  0.11941
+1.00    0.14978  0.08884  0.11941  0.11941
-1.00    0.08884  0.14978  0.11941  0.11941
```

The X pair splits, the Y pair is untouched, and the two directions mirror.

## Exposure decides detection

The single most important setting for detection is the camera exposure, not
the colour gate. Measured on this rig at exposure -6 with gain 110, **55% of
the ball was clipped to pure white** -- V=255, saturation 0, hue meaningless.
There is no colour left in a clipped pixel, so no threshold can recover it: the
mask became a crescent of the ball's shaded side, and the centre of that
crescent sat **35 px (7 mm) away from the ball's true centre**, consistently,
in the direction of the highlight. A steady bias like that does not average
out; the controller simply chases the wrong place.

Widening the gate cannot fix it, and the sweep says so plainly -- every
combination of hue and saturation gave 35-36 px. Nor can geometry: fitting a
circle to the crescent's boundary (algebraic and RANSAC both tried) reached
28.7 px at best, because the mask was eroded all round rather than merely cut
on one side.

At exposure **-8 with gain 60** nothing clips, and the numbers change
completely:

| | before | after |
|---|---|---|
| median centre error | 35.2 px (7.2 mm) | **0.8 px (0.2 mm)** |
| radius reported | 90 px, true 139 | 97 px, true 100 |
| frame-to-frame jitter | - | 1.1 px |
| live detection rate | 94% | 40 of 40 |

*(The shipped camera setting is now exposure -8 with gain 120, and the value
floor has since been lowered to `V>=15` with a 7 px kernel and a fill gate -- a
floor of 50 was cutting away the ball's shaded half. The measurement above is
kept because it is the evidence for the principle.)*

The gate that suits that image is `H 0..20, S>=150, V>=50`. **Saturation is what
separates ball from background**, and it can be that strict only because the
ball is no longer blown out: 95% of its pixels sit at S=255 while the ceiling
is grey. Value cannot do the separating -- the background reaches V=110 and the
ball starts at V=101 -- which is why the value floor is deliberately loose and
only rejects sensor noise.

**So check for clipping before touching the colour gate.** If the ball's
histogram piles up at V=255, the exposure is the fault and everything
downstream is guesswork.

## Which blob is the ball

A single frame cannot say. A ball whose lit side falls outside the colour gate
breaks into several contours, and background clutter can be rounder than any of
them. `BallTracker` uses continuity between frames instead:

- **Plate region.** Candidates further than `vis_roi_radius` from frame centre
  are discarded outright. The ball is on the plate and the plate is centred, so
  this is the strongest geometric evidence available, and the ball's centre has
  far less travel than that before it clips the frame edge anyway.
- **Trust is earned.** A new candidate must hold within `vis_lock_tol_px` for
  `vis_lock_frames` consecutive frames before it is believed. Until then the
  answer is "no ball", which every caller already treats as wait-and-do-nothing.
- **Then tracked by proximity**, within `vis_gate_px` of the last accepted
  position, with the lock dropped after `vis_gate_frames` consecutive misses so
  a ball that is picked up and put back somewhere else is found again.

The cold-start rule is the subtle one: it picks the candidate nearest the
centre of the plate, **not** the largest. Taking the largest is what latches
onto background, and once latched the proximity gate defends that choice
forever, because something that never moves always looks like the same thing,
still nearby. The lock has to be earned before it is trusted, not assumed and
then defended.

Detection is therefore stateful, and one frame can never produce a ball. Call
`VisionProcessor.reset()` when a run starts; the GUI does this on arming so a
lock earned while idle is not inherited.

**Tune the colour gate on a frame captured through this application**, not on a
raw `cv2.VideoCapture` grab. The app pushes saturation, contrast and gain into
the camera, and those move the whole scene: on a raw capture a plain ceiling
sits well below the saturation floor, while through the app the same ceiling
reaches a median of 64. A gate tuned on the wrong image looks fine in the
measurement and admits half the background in use.

## Which way does the plate push the ball

If a commanded tilt moves the ball the wrong way the loop accelerates it
outward instead of catching it, and the ball leaves every time — which reads as
gains being wrong, or the plate being too aggressive, rather than as a mapping
fault. `ctl_swap_axes`, `ctl_invert_x` and `ctl_invert_y` describe the mapping;
there are eight combinations and trying them by hand costs a ball roll each.

```
python signtest.py            measure and report
python signtest.py --apply    and write the result into the parameters
```

It tilts ±2 deg on each axis and measures the ball's response. Three details
are what make it work on a plate with no rim:

- **Velocity, not position.** Under a constant tilt the ball accelerates, so
  where it ends up after a fixed time depends on where it started. How fast it
  is moving does not.
- **Both directions, differenced.** A plate slightly off level, or a ball
  already drifting, adds the same bias to the + and - legs; subtracting them
  cancels it. A single leg measures the bias as much as the response.
- **A centimetre of travel per leg**, and each tilt is unwound by the opposite
  one for twice as long, which brings the ball back near rest.

It also reports the angle between the two response directions. That must be
near 90 deg: if the two tilt commands act on nearly the same physical
direction, no swap or invert can express the mapping and the fault is the motor
pairing (`machine.MOTOR_ORDER`) instead.

**The plate has no rim, and that is the practical obstacle.** A cardboard
collar or a tape lip around the edge makes this measurement and every tuning
step after it straightforward. Without one the ball may leave mid-measurement —
the tool says so rather than reporting a guess.

## Modes

Five, picked on the Session tab; the numbers live on the Modes tab.

| mode | what it does |
|---|---|
| **Balancing** | holds the ball at the balancing height, indefinitely |
| **Balance then rest** | holds it lively for a while, then softens the gains so it slows and stops in the middle |
| **Balance and juggle** | holds it centred, and throws a hop every few seconds |
| **Juggling** | bounces continuously, four phases per cycle (35 → 51 mm by default) |
| **Juggle routine** | a structured sequence modelled on the Unity host's Full Juggling Demo: warm-up bounces, then walking the target out and back and tracing a small circle, with settling cycles between legs |

### Juggling is supervised

The camera's window is narrow, so a drifting ball is lost long before the plate
runs out of travel. Both juggling modes therefore treat "centred" as something
to keep earning:

- **Throwing only starts** once the ball is within `mod_jug_centre_px` (40 px)
  and slower than `mod_jug_centre_speed` (120 px/s) for `mod_jug_centre_hold`
  (8) consecutive commands.
- **Throwing stops** and the plate falls back to balancing whenever the ball
  drifts beyond `mod_jug_keep_mm` (30 mm) or is unseen for
  `mod_jug_lost_seconds` (0.4 s). The routine also resets its target to the
  centre.
- **While re-centring, the rest gains are swapped in**, which bring the ball in
  faster than the lively juggling gains.
- **If the plate was at the top of a stroke, it comes down over the fall time.**
  Dropping 16 mm in a short balancing move is about 2 g, which pulls the plate
  out from under the ball and throws it again.

### Sizing a hop

**Commanded acceleration does not predict whether the ball leaves the plate on
this machine.** Measured: 30 mm in 0.10 s (1.51 g) separates it, while 20 mm in
0.08 s -- a *higher* 1.57 g -- does not. The short stroke gives the motors too
little time to reach the speed being asked for, so they under-deliver. If the
ball is not leaving the plate, go **bigger and slower**, not faster.

30 mm in 0.10 s is the smallest proven hop, leaving at 0.47 m/s for an 11 mm hop
with about 0.10 s of air; the shipped *Balance and juggle* default is now a
larger 50 mm in 0.11 s (`mod_hop_mm`, `mod_hop_rise`). The plate then holds still at the top for
that airborne time, so the ball lands on a stationary surface rather than a
moving one, and returns down twice as slowly -- the fall throws nothing, so
speed there is only shaking the frame.

**Tilt stays live through every phase, the airborne one included.** The plate
has to be in the right place when the ball comes down, and levelling during the
hop throws away exactly the correction that would put it there.



The Session tab picks a mode and starts it; the Modes tab holds the numbers.

**Balancing** rises once to `mod_balance_height` (30 mm above the working
origin by default) over `mod_rise_time`, waits `mod_settle_time`, then holds
that height and issues a tilt every `mod_balance_move_time`. No tilt is applied
during the climb: the ball has nothing useful to say while the platform is
still moving vertically, and correcting against a rising plate only fights it.

**Juggling** runs a four-phase cycle at that height: a fast rise that throws the
ball, a dwell while it is airborne, a deliberately slower fall, and a dwell at
the bottom. Only the rise needs to beat 1 g; the fall launches nothing, so
speed there is structural excitation for no benefit, and the dwells let the
frame stop ringing between strokes. The panel reports the rise's peak in g, and
says plainly when it is too gentle to lift the ball off the plate. Tilt is
corrected on every phase, including the fall and the bottom dwell, because
those are when the ball is in contact and can actually be rolled toward centre.

**A long move is sent once and then left alone.** The firmware clears its
queued batches and restarts on every line it receives, and each move is a
half-cosine that begins at rest -- so re-sending the same target every control
tick restarts the profile from zero velocity and the plate crawls upward at a
few mm/s while the log looks perfectly healthy. `ModeRunner.command()` returns
`None` to mean "a move is still running, do not interrupt it". That is why the
mode owns the cadence rather than the control loop.

Arming requires an open port. Without one the loop would run and the mode would
advance through its phases with nothing reaching a machine.

## When it looks like nothing is happening

The firmware is built with `VERBOSE_SERIAL_LOGGING` set to `0`. It answers
`PING` with `PONG`, prints a rejection for a batch whose marker is wrong, and
**says nothing else at all** — not for a move it accepted, not for a line it
could not parse. A healthy link is therefore almost entirely silent, and an
empty monitor is the normal state rather than a symptom.

Two scripts settle it without guessing. Nothing else may hold the port while
they run — Windows allows one owner, so close the GUI first:

```
python hwtest.py            bare pyserial: is the board alive?
python hwtest.py --move     ... and does it move?
python workertest.py        the same, through the app's own SerialWorker
python workertest.py --move
```

`hwtest.py` sends a deliberately bad marker, which is the one malformed input
the firmware does complain about — a reply proves the parser is running and
reading our fields, not merely that the cable is plugged in. If `hwtest` passes
and `workertest` fails, the fault is in the application; if both pass and the
plate still does not move, it is past the microcontroller: driver enable, motor
power, or the DM542T wiring.

## Bringing the machine up

The *Machine* tab exists because a control loop cannot be debugged before the
three things under it are known to work, in this order:

1. **Go to ORIGIN** — level, at the working origin. The plate at rest has no
   downward travel -- and the structure interferes near the bottom -- so the
   working origin is parked 20 mm above it (`mac_origin_offset`) to give the
   loop room to move either way.
2. **Height, no tilt** — a pure vertical move proves all four arms are driven,
   wired the same way round, and agree with each other. If the plate skews, the
   fault is mechanical or in `MOTOR_ORDER`, not in the control maths.
3. **Tilt** — one axis at a time, then the sweep. If both axes tip the plate the
   same physical way, `MOTOR_ORDER` in `machine.py` pairs the arms wrongly.

Every button prints the line it sent and the per-motor angle and pulse count
behind it, so a plate that does not move can be diagnosed as bad numbers or bad
motors without reaching for a scope.

## First run

1. **Camera** tab — set the device index. If the picture is dark, raise Gain
   before lengthening Exposure: a long exposure smears a moving ball, and
   motion blur costs more than noise does.
2. **Vision** tab — tick *Show mask* and adjust the HSV range until the ball is
   solid white and nothing else is. Tune with the mask visible; tuning against
   the colour image is guesswork. Untick it when you are done.
3. **Serial** tab — *Refresh ports*, pick the `COMx`, *Connect*. Telemetry
   should start scrolling if the firmware is sending it.
4. **Control** tab — set *Max tilt* low (2–3°) for the first run.
5. **Session** tab — *Start control*. Click the video to move the target.

### Getting the axis signs right

The camera's axes almost never match the plate's first time. With the ball
resting off-centre and the loop running, watch which way the plate moves. Use
*Swap axes*, *Invert X* and *Invert Y* until a ball sitting to the right makes
the plate lift on the right. If the ball accelerates away instead of returning,
a sign is wrong — no amount of gain tuning fixes that, and raising the gain
makes it leave the plate faster.

## Tuning the controller

Start from `Kd`, not `Kp`. A ball on a plate is a double integrator with a
transport delay, and such a plant needs the derivative term to be stable at
all; proportional-only control oscillates with growing amplitude no matter how
small the gain. `simtest.py` demonstrates both cases.

Measured behaviour of an earlier gain pair (`Kp` 0.05, `Kd` 0.07) against the
simulated plant -- the shipped defaults are now softer (0.02 / 0.04), but the
delay trend is the lesson and still holds:

| loop delay | result |
|---|---|
| 15–100 ms | settles, no overshoot |
| 150 ms | still settles, but rings noticeably |
| 200 ms and up | does not settle — re-derive the gains |

The *control* trace on the rate plot is the number that matters here. If it
falls, the delay rises and the gains that were right become wrong.

## Emergency stop

`Esc` or `Space`, or the red button. It disarms the loop, commands 0° and
commands the plate level at the working origin in the shortest move the
firmware accepts. Re-arming with *Start control* clears it. Closing the window
levels the plate before the process exits.

## Tests

```
python selftest.py    # parameters, velocity estimation, PID, mirror law, vision, logging
python machinetest.py # kinematics and the wire format
python modetest.py    # the mode state machine, against an injected clock
python guitest.py     # the real window offscreen: threads, and every button clicked
python simtest.py     # closed-loop simulation against a modelled ball and plate
```

`selftest` and `simtest` need no hardware; `guitest` runs headless. All three
exit non-zero on failure, so they can be wired into a pre-commit hook.

## Every script, at a glance

The application itself is `main.py` plus the modules listed at the top. Everything else is a tool
that does one job, run from this folder. The hardware ones need the serial port to themselves, so
close the GUI first.

| Script | Purpose | Hardware? |
|---|---|---|
| `selftest.py` · `machinetest.py` · `modetest.py` · `simtest.py` | Parameters, vision, kinematics, wire format, mode state machine, closed-loop simulation | no |
| `guitest.py` | Builds the real window offscreen and clicks every button | no |
| `optics.py` | Camera window and throw physics model (also importable) | no |
| `hwtest.py` · `workertest.py` | Is the board alive, and does it move? `--move` also moves the plate | yes |
| `park.py` | Put the plate back on the calibrated level origin | yes |
| `movetest.py` | Presses the Machine tab's buttons for real | yes |
| `signtest.py` · `mappingsearch.py` · `pairingtest.py` | Which way the plate pushes the ball; the axis mapping; which arms pair | yes |
| `autolevel.py` · `centretrim.py` · `backlashtest.py` | Levelling and play, using the ball as the instrument | yes |
| `exposuretest.py` · `heighttest.py` | Exposure that measures the ball at true size; visibility when raised | yes |
| `livetest.py` | The oscillation, with the whole GUI alive around it | yes |
| `unitycheck.py` | Confirms the two hosts agree on **hardware** facts only; reports tuning side by side without judging it | no |

## Notes on two defaults that are not obvious

**`vis_hough_p2` is 16, not the more usual 32.** The transform runs on the
binary mask, whose thinned edges cast far fewer accumulator votes than a grey
image's would. Measured on synthetic balls from 10 to 160 px radius, 32 finds
nothing at any size while 16 finds all of them with no false positives.

**Detection runs on the capture thread, not its own.** The control loop wants
the newest ball position, not every position. Queueing frames to a second
worker would add latency and a backlog to drain. Display is throttled to about
30 Hz independently, so the screen never limits the control rate.
