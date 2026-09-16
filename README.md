# Dynamic Platform — a camera-guided ball balancing and juggling robot

A four-arm parallel platform that balances and juggles a 40 mm ball. A camera **underneath a
transparent plate** tracks the ball, a PC computes the plate tilt and height that bring it back to
the target, and a Teensy 4.0 turns that pose into step pulses for four geared stepper motors.

This repository is the thesis project built on Tobias Kuhn's open-source
[HighPrecisionStepperJuggler](https://github.com/T-Kuhn/HighPrecisionStepperJuggler) (MIT). The
original firmware and Unity application are kept and extended, rebuilt around different hardware,
and joined by a second, independent PyQt5 host application.

---

## Contents

1. [Two host applications, one machine](#two-host-applications-one-machine)
2. [Repository layout](#repository-layout)
3. [Hardware](#hardware)
4. [Firmware (Teensy 4.0)](#firmware-teensy-40)
5. [Host A — PyQt5 application](#host-a--pyqt5-application)
6. [Host B — Unity application](#host-b--unity-application)
7. [The camera: why field of view governs everything](#the-camera-why-field-of-view-governs-everything)
8. [Motion physics worth knowing](#motion-physics-worth-knowing)
9. [Known issues and traps](#known-issues-and-traps)
10. [Thesis tooling](#thesis-tooling)
11. [Working with this repository](#working-with-this-repository)
12. [Credits and licence](#credits-and-licence)

---

## Two host applications, one machine

There are **two completely separate programs** that can drive the machine. They share the hardware
and the firmware and nothing else.

| | **PyQt5 app** | **Unity app** |
|---|---|---|
| Folder | [`pyballbalancer/`](pyballbalancer/) | [`HighPrecisionStepperJuggler-master/Unity/`](HighPrecisionStepperJuggler-master/Unity/) |
| Language | Python 3 | C# (Unity 2019.2.23f1) + a C++ OpenCV plugin |
| Camera frame | 640 × 480 landscape | 480 × 640 portrait |
| Controller gain units | degrees per **pixel** | degrees per **millimetre** |
| Tuning | live, from GUI tabs; saved as JSON presets | `Constants.cs` defaults, overridden by Inspector values in the scene |
| Visualisation | video, mask, live plots | 3D digital twin, camera view, gradient-descent telemetry panel |

**Do not treat one as a reference for the other.** They use different frame orientations,
different unit systems and different calibrations, so the same number means something different in
each. A value that works in one host is not evidence about the other. The tuning tables below are
kept per host deliberately. Only the physical facts — the linkage, the camera optics, the firmware
protocol — are shared.

Only one of them can hold the serial port at a time. Close one before starting the other.

---

## Repository layout

```
Thesis/
├── pyballbalancer/                  Host A: PyQt5 control application        → its own README
├── HighPrecisionStepperJuggler-master/
│   ├── Arduino/HighPrecisionStepperJuggler/   Teensy 4.0 firmware (used by BOTH hosts)
│   ├── Unity/HighPrecisionStepperJuggler/     Host B: Unity project
│   ├── Unity/ScriptableRenderPipeline-6.9.1/  HDRP package the Unity project depends on
│   ├── UVCCameraPlugin/                       C++ source of the Unity camera plugin (OpenCV)
│   ├── Latex/                                 Original author's paper source
│   └── LICENSE                                MIT, Tobias Kuhn
├── codes/                           Standalone Teensy test sketches and a Python env check
├── tools/                           Scripts that build the thesis figures and draft document
├── Design/                          Fusion 360 models and arm drawings (.f3d, .pdf)
├── stl files/                       Printable parts (.stl, .3mf) and the full assembly (.step)
├── datasheets/                      Teensy, DM542T, NEMA17, buck converters, level shifter
├── my_documents/                    Wiring diagrams, photos, screen recordings
├── log files/                       Captured Editor/balancing logs and calibration CSV
├── Thesis Report/                   Thesis document (git submodule pointer — see below)
└── campus_cham_leitfaden_abschlussarbeiten_en.pdf   University thesis guidelines
```

---

## Hardware

### Parts

| Part | Detail |
|---|---|
| Microcontroller | Teensy 4.0 |
| Stepper drivers | 4 × StepperOnline **DM542T** |
| Motors | 4 × NEMA17 **17HS19-1684S-PG5** — 1.8°/step, **5.18:1** planetary gearbox, 1.68 A/phase |
| Power | 24 V / 8 A supply; buck converter for the 5 V rail |
| Linkage | 4 arms, `L1 = 89 mm`, `L2 = 80 mm`, plate joints 299 mm apart, `Q = 70.023 mm` |
| Camera | UVC USB camera, 60.41° horizontal FOV, mounted **below** a transparent plate |
| Ball | 40 mm diameter (radius 20 mm) |

Datasheets for all of these are in [`datasheets/`](datasheets/); CAD is in [`Design/`](Design/)
and [`stl files/`](stl%20files/).

### Wiring (Teensy → DM542T)

Pin numbers are fixed in the firmware's `Constants.h`:

| Motor | STEP pin | DIR pin |
|---|---|---|
| 1 | 6 | 5 |
| 2 | 2 | 1 |
| 3 | 4 | 3 |
| 4 | 8 | 7 |

Common-cathode wiring: `PUL-` and `DIR-` to Teensy GND, the `+` inputs driven from the Teensy pins,
`ENA` left unconnected (enabled). Diagrams are in
[`my_documents/connection diagrams/`](my_documents/connection%20diagrams/).

> **Signal levels.** The Teensy is a 3.3 V part and the DM542T inputs are optocouplers specified
> for 5 V. The TXS0108E level shifter could not source enough current for them and was bypassed, so
> the signals are driven directly at 3.3 V. That works, but under-drives the opto inputs. The
> robust fix is a 5 V buffer such as a 74HCT541, or one NPN transistor per line.

### DM542T DIP switches

| Setting | Switches | Value |
|---|---|---|
| Microstepping | SW5 ON, SW6 ON, SW7 OFF, SW8 ON | **1/16 → 3200 pulses per motor rev** |
| Current | SW1 ON, SW2 OFF, SW3 ON | 1.36 A RMS / 1.91 A peak |
| Standstill | SW4 OFF | current halved at rest |

**The microstep setting and the firmware must agree.** `PULSES_PER_REV` in `Constants.h` is
`200 × microsteps × 5.18` = `200 × 16 × 5.18` = **16576**. If you change the DIP switches, change
that constant and re-upload, or every move produces the wrong pulse count and the motors stall.
Never change DIP switches or unplug a motor with the driver powered.

---

## Firmware (Teensy 4.0)

Location: [`HighPrecisionStepperJuggler-master/Arduino/HighPrecisionStepperJuggler/`](HighPrecisionStepperJuggler-master/Arduino/HighPrecisionStepperJuggler/)

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

[`codes/`](codes/) holds bare STEP/DIR test sketches (`motorTest`, `allmotor`, `fixedmove`, …) for
checking drivers and motors without the full firmware.

---

## Host A — PyQt5 application

Location: [`pyballbalancer/`](pyballbalancer/). **Its README is the detailed manual:**
[`pyballbalancer/README.md`](pyballbalancer/README.md).

### Quick start

```
cd pyballbalancer
pip install -r requirements.txt        # PyQt5, opencv-python, pyqtgraph, numpy, pyserial
python main.py
```

Then: **Serial** tab → pick the COM port → Connect. **Machine** tab → *Go to ORIGIN*. **Session**
tab → pick a mode → *Start control*. **Esc** or **Space** is the emergency stop. Close the window
normally rather than killing the process, because closing parks the plate level on the way out.

### What it does

Capture, detection, control and serial I/O each run on their own thread. Every tunable value is
declared once in `params.py`, and the GUI tabs are generated from that list, so everything can be
changed live without a restart. **Save…/Load…** writes and reads a JSON preset; `preset.json` is the
current working set.

### Modes

| Mode | Behaviour |
|---|---|
| **Balancing** | Holds the ball at the balancing height indefinitely. |
| **Balance then rest** | Holds it lively for a while, then blends to softer gains so it slows and stops in the middle. |
| **Balance and juggle** | Holds it centred and throws a single hop every few seconds. |
| **Juggling** | Continuous four-phase bounce: fast rise, top dwell, slow fall, bottom dwell. |
| **Juggle routine** | A structured sequence modelled on the original Full Juggling Demo: warm-up bounces, then walking the target and tracing a small circle. |

Both juggling modes are **supervised**. They only start throwing once the ball has been centred and
slow for several consecutive commands. They suspend the throwing and fall back to balancing when the
ball drifts past `mod_jug_keep_mm` (30 mm) or is lost for `mod_jug_lost_seconds` (0.4 s). Coming
down from the top of a stroke uses the slow fall time, never a fast move.

### Current calibration on this rig (PyQt host only)

| Setting | Value |
|---|---|
| Arm pairing | `0+2 / 1+3` |
| Working origin | 20 mm above the mechanical dead position |
| Level trim | X −0.40°, Y −0.40°, **levelled at 35 mm** (`mac_trim_height`) |
| Axis mapping | swap / invert X / invert Y all off |
| PID | Kp 0.02, Ki 0.10, Kd 0.04 per axis; integral clamp 20; gains scaled with ball radius |
| Limits | max tilt 3°, max tilt rate 25°/s, command rate 100 Hz |
| Camera | exposure −8, gain 120 |
| Detection | HSV H 0–20, S ≥ 150, V ≥ 15; kernel 7; min fill 0.80; min circularity 0.30 |
| Juggling stroke | 35 → 51 mm; rise 0.05 s, top 0.07 s, fall 0.16 s, bottom 0.14 s |

**The level trim belongs to a height, not to the machine.** The linkage has a residual slope that
changes along its travel, so a plate levelled at the origin is not level at the height the loop
actually runs at. Level at the working height; the Machine tab moves the plate there before nudging.

### Tools and tests

| Script | Purpose |
|---|---|
| `selftest.py` · `machinetest.py` · `modetest.py` · `simtest.py` | Headless tests: parameters, vision, kinematics, wire format, mode state machine, closed-loop simulation |
| `guitest.py` | Builds the real window offscreen and clicks every button |
| `hwtest.py` · `workertest.py` | Is the board alive, and does it move? Use `--move` to also move the plate. |
| `park.py` | Put the plate back on the calibrated level origin |
| `signtest.py` · `mappingsearch.py` · `pairingtest.py` | Which way the plate pushes the ball; axis mapping; which arms pair |
| `autolevel.py` · `centretrim.py` · `backlashtest.py` | Levelling and play, using the ball as the instrument |
| `exposuretest.py` · `heighttest.py` | Exposure that measures the ball at true size; visibility when raised |
| `optics.py` | Camera window and throw physics model (validated against the rig) |
| `unitycheck.py` | Confirms the two hosts agree on **hardware** facts only; reports tuning side by side without judging it |

Hardware scripts need the port to themselves, so close the GUI first.

---

## Host B — Unity application

Location: [`HighPrecisionStepperJuggler-master/Unity/HighPrecisionStepperJuggler/`](HighPrecisionStepperJuggler-master/Unity/HighPrecisionStepperJuggler/)

The Unity application is responsible for:

- Setting up the camera (120 FPS stream, gain, exposure, contrast, saturation) and receiving images, via OpenCV
- Running image processing to get the 2D pixel position and radius of the ball
- Getting the 3D position of the ball from those results (radius → distance from the camera)
- Estimating ball velocity, using a small least-squares fit solved by gradient descent
- Using ball position and velocity in the PID or analytical controller to compute the correction tilt
- Running the inverse kinematics that turn a plate height and tilt into four motor angles
- Sending the result to the microcontroller over serial
- Rendering the machine, the image-processing output, and live telemetry graphs

[`UVCCameraPlugin/`](HighPrecisionStepperJuggler-master/UVCCameraPlugin/) contains the C++ source of
the camera plugin. All the OpenCV code runs inside it.

### Setup

1. **Use Unity Editor 2019.2.23f1.** It is the version recorded in `ProjectSettings/ProjectVersion.txt`.
   Newer versions will not open the project cleanly.
2. **OpenCV runtime.** The camera plugin is built against **OpenCV 4.13.0**.
   `opencv_world4130.dll` must sit next to `UVCCameraPlugin.dll` in
   `Assets/Plugins/UVC Camera Plugin/`. It is committed there already. If it goes missing, copy it
   from the `bin` folder of the OpenCV 4.13.0 Windows release, or you will see:
   ```
   Plugins: Failed to load 'Assets/Plugins/UVC Camera Plugin/UVCCameraPlugin.dll' because one or more of its dependencies could not be loaded.
   ```
3. Open `Assets/HighPrecisionStepperJuggler/MainScene.unity`.
4. In the Inspector, check:
   - **`SerialInterface` → Port Name**: your Teensy's port (currently `COM3`). An empty value or `off` disables serial.
   - **`MachineController` → Machine End Point**: `Real` or `ModelAndReal`. `Model` only moves the
     on-screen twin and nothing reaches the Teensy.
   - **`ImageProcessingInstructionSender` → Strategy Program**: see below.

### Strategy programs

| Program | Behaviour |
|---|---|
| **BalancingOnly** | Waits for the ball, then balances indefinitely with PID. Start here. |
| **FullJugglingDemo** | The original ~100-stage choreography. It starts striking the ball about 2 s in, so the ball leaving the plate is intended. It asks for more travel than this camera can see (see below). |
| **SmallJugglingDemo** | Settle, a bounded set of gentle 10 mm bounces, then land. |
| **OscillatingJuggling** | A fixed four-phase clock (rise, dwell, fall, dwell) with PID tilt. With `AimTheThrow` on, the analytical controller aims the rise. It is supervised: past 30 mm it stops throwing and balances the ball back, and resumes once the ball has held within 8 mm and under 25 mm/s for 8 commands. |

### Keyboard controls (Play mode)

| Key | Action |
|---|---|
| **Space** | Arm / disarm the selected strategy program. Arming forces a detection image mode. |
| **O** | Go to working origin |
| **H** | Go to mechanical zero |
| **1 – 9** | Go to height 10 … 90 mm · **0** → 2 mm |
| **Arrow keys** | Small test tilts |
| **M / B** | Next / previous image-processing mode · **N** shows its caption |
| **C** | Measure the camera→plate axis mapping (tilts the plate and watches the ball roll) |
| **P** | Measure delivered tilt and static slope, using the ball as an inclinometer |
| **R** | Search for the correct motor pairing |
| **L** | Toggle ball-position logging |
| **I / X** | Log a ball calibration sample at origin / at max distance |
| **T** | Toggle ball trail · (also sends a single-motor test move) |
| **Y** | Ping the Teensy |
| **F2** | Toggle debug GUI |

The **MachineController Inspector** has buttons for the origin, mechanical zero, test heights and
tilts, a backlash reversal cycle, and **level-trim nudges** (X/Y −/+, reset, re-send origin).

**Ball detection only produces real data in the detection image modes.** Every other mode returns
a placeholder ball. Arming with Space switches mode for you, but if you cycle with M/B while armed
you can blind the controller.

### Current calibration on this rig (Unity host only)

| Setting | Value |
|---|---|
| Motor wiring order | `{0, 2, 1, 3}` |
| Working origin | 20 mm above the mechanical dead position (`OriginHeightOffset`) |
| Level trim | X −0.80°, Y −1.30° (applied at the origin) |
| Axis mapping (scene) | swap ✔, invert X ✘, invert Y ✔ |
| PID | k_p 0.111, k_i 0.555, k_d 0.222 (deg per mm); integral clamp 20° |
| Limits | tilt ±3°, max tilt rate 25°/s (PID only) |
| Balancing move time | 0.06 s |
| Camera | exposure −8, gain 120; frame 480 × 640 portrait |
| Size gate | expected ball radius × 1.25 |
| OscillatingJuggling | 35 → 51 mm; rise 0.05 s, top 0.07 s, fall 0.16 s, bottom 0.14 s |

> **Inspector values override `Constants.cs` and C# field defaults.** Any `[SerializeField]` value
> already saved in `MainScene.unity` wins over the number in code. After changing a default, check
> the scene file too, or Play mode will quietly bring the old value back.

### Reading the Gradient Descent View

The black telemetry panel shows ball history as two traces. **Green is X**, drawn with time running
downward. **Orange is Y**, drawn with time running leftward. The yellow cross is the ball now and
the red cross is the commanded target. The thick bars are 6-sample line fits: where a bar starts is
the position estimate and how steeply it leans is the velocity, and both are what the controllers
use. The short ticks on the top and right edges are the predicted landing point, shown only by
bouncing strategies.

---

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

## Known issues and traps

| Issue | Effect | Status |
|---|---|---|
| Level trim depends on height | Levelling at the origin leaves a slope at the working height | Fixed in PyQt (`mac_trim_height`); Unity still levels at the origin |
| Unity Inspector overrides code defaults | A changed `Constants.cs` or field default appears to be ignored | By design in Unity; always check `MainScene.unity` |
| `BallData.AirborneTime` clamped to ≥ 0.1 s (Unity) | Analytical controller underestimates the lateral speed needed on short hops, so it aims short | Open |
| Analytical controller has no integrator and no rate limit (Unity) | A standing plate slope is never trained out while it is in charge | Open |
| `MaxPlateHeight = 90f` is in the wrong units (Unity) | The height clamp never engages (heights are in metres) | Open |
| Full Juggling Demo targets ±40 mm | Target lies outside the clean camera window; `BouncingStrong` exceeds arm reach | Open, inherited from original |
| Killing a host instead of closing it | Plate is left at its last tilt, which looks like lost calibration | Close normally, or run `park.py` / press **O** |
| Two programs on one COM port | Second one silently cannot send | Close the other host or the Arduino Serial Monitor |
| 3.3 V drive into 5 V opto inputs | Reduced noise margin and step-rate headroom | Hardware; see Wiring |

---

## Thesis tooling

| Script | Output |
|---|---|
| [`tools/gen_figs.py`](tools/gen_figs.py) | IK geometry, sine motion profile and camera FOV diagrams |
| [`tools/gen_block.py`](tools/gen_block.py) | System block diagram (`fig_block.png`) |
| [`tools/make_thesis.py`](tools/make_thesis.py) | Rebuilds the draft `.docx` from the figures (`python-docx`; set `THESIS_DIR` / `FIG_DIR`) |
| [`codes/test_setup.py`](codes/test_setup.py) | Confirms the Python / OpenCV / NumPy environment |

---

## Working with this repository

- **Git LFS is required.** Binary assets such as the Unity DLLs are stored with LFS. Run
  `git lfs install` before cloning, or those files arrive as small pointer text files.
- **Unity's `Library/` folder is tracked** and Unity rewrites parts of it, along with some `.mat`
  files, whenever the editor is open. Close Unity before committing to keep that churn out of the
  history.
- **`Thesis Report/` is a submodule pointer with no `.gitmodules` entry.** It appears empty in a
  fresh clone; the document lives outside this repository.
- **Low commit memory breaks Git LFS on Windows.** If `git add` fails with a Go
  `out of memory allocating heap arena map` error, close Unity (or enlarge the page file) and retry.
- **`.mcp.json`** configures an Overleaf MCP server for editing the thesis. It reads
  `OVERLEAF_PROJECT_ID` and `OVERLEAF_GIT_TOKEN` from the environment and contains no secrets.

---

## Credits and licence

- Firmware, Unity application, camera plugin and the original paper: **Tobias Kuhn**,
  [HighPrecisionStepperJuggler](https://github.com/T-Kuhn/HighPrecisionStepperJuggler) and the
  related [Octo-Bouncer](https://www.electrondust.com/2020/03/01/the-octo-bouncer/). MIT licence, see
  [`HighPrecisionStepperJuggler-master/LICENSE`](HighPrecisionStepperJuggler-master/LICENSE).
- Hardware rebuild, firmware fixes, Unity extensions, the PyQt5 application and all calibration in
  this repository: **Anandhu Vijayan**, as part of a thesis at Deggendorf Institute of Technology,
  Campus Cham.
