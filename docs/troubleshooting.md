# Troubleshooting, known issues and traps

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

## When it looks like nothing is happening

The firmware is nearly silent by design: it answers `PING` with `PONG`, complains about a bad batch
marker, and says nothing else — not for a move it accepted, not for a line it could not parse. An
empty serial monitor is the normal state, not a symptom.

To tell a dead link from a dead motor, from the PyQt app's folder and with the GUI closed:

```
python hwtest.py            bare pyserial: is the board alive?
python hwtest.py --move     ... and does it move?
python workertest.py        the same, through the app's own serial worker
```

If `hwtest` passes and the plate still will not move, the fault is past the microcontroller: driver
enable, motor power, or the DM542T wiring.

## The plate sits tilted after a crash

The motors hold the last pose they were given, so anything that exits without tidying up leaves the
plate leaning. It looks exactly like lost calibration and is not. Run `python park.py` in
`pyballbalancer/`, or press **O** in Unity.

---

[← Back to the main README](../README.md) · [Hardware](hardware.md) · [Firmware](firmware.md) · [PyQt app](../pyballbalancer/README.md) · [Unity app](unity-app.md) · [Camera & motion](camera-and-motion.md) · [Troubleshooting](troubleshooting.md) · [Repository](repository.md)
