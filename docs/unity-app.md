# Unity application — setup and use

Location: [`HighPrecisionStepperJuggler-master/Unity/HighPrecisionStepperJuggler/`](../HighPrecisionStepperJuggler-master/Unity/HighPrecisionStepperJuggler/)

The Unity application is responsible for:

- Setting up the camera (120 FPS stream, gain, exposure, contrast, saturation) and receiving images, via OpenCV
- Running image processing to get the 2D pixel position and radius of the ball
- Getting the 3D position of the ball from those results (radius → distance from the camera)
- Estimating ball velocity, using a small least-squares fit solved by gradient descent
- Using ball position and velocity in the PID or analytical controller to compute the correction tilt
- Running the inverse kinematics that turn a plate height and tilt into four motor angles
- Sending the result to the microcontroller over serial
- Rendering the machine, the image-processing output, and live telemetry graphs

[`UVCCameraPlugin/`](../HighPrecisionStepperJuggler-master/UVCCameraPlugin/) contains the C++ source of
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
   - **`ImageProcessingInstructionSender` → Strategy Program**: see [Strategy programs](#strategy-programs) below.

### Strategy programs

| Program | Behaviour |
|---|---|
| **BalancingOnly** | Waits for the ball, then balances indefinitely with PID. Start here. |
| **FullJugglingDemo** | The original ~100-stage choreography. It starts striking the ball about 2 s in, so the ball leaving the plate is intended. It asks for more travel than this camera can see — see [camera-and-motion.md](camera-and-motion.md). |
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

The PyQt application is separate and documented in [../pyballbalancer/README.md](../pyballbalancer/README.md). Do not copy tuning between them — see [the main README](../README.md#two-hosts-one-machine).

---

[← Back to the main README](../README.md) · [Hardware](hardware.md) · [Firmware](firmware.md) · [PyQt app](../pyballbalancer/README.md) · [Unity app](unity-app.md) · [Camera & motion](camera-and-motion.md) · [Troubleshooting](troubleshooting.md) · [Repository](repository.md)
