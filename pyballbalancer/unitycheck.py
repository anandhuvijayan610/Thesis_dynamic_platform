"""Compare this host's settings with the Unity host's, side by side.

The two are SEPARATE PROGRAMS that happen to drive the same machine. They are
tuned independently and are expected to differ - a different trim, different
gains, a different camera exposure are all legitimate, because each was set
against its own detector and its own control loop. This tool does not try to
make them agree.

What it does assert is the small set of facts that describe the MACHINE and the
CAMERA rather than either program's tuning: link lengths, plate width, the
plate's rest height, the arm pairing, and the optical constants this host's
camera model was fitted against. Those are measurements of the world. If they
disagree, one of the two is simply wrong about the hardware, and every pose it
commands or every height it reports will be wrong with it.

Everything else is printed for comparison and carries no verdict.

    python unitycheck.py

No hardware, no Unity, no serial port.
"""
from __future__ import annotations

import os
import re
import sys

import machine
import optics
from params import ParameterStore

HERE = os.path.dirname(os.path.abspath(__file__))
UNITY = os.path.join(HERE, "..", "HighPrecisionStepperJuggler-master", "Unity",
                     "HighPrecisionStepperJuggler", "Assets",
                     "HighPrecisionStepperJuggler")
SCRIPTS = os.path.join(UNITY, "Scripts")

FAILED = []


def read(path):
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return fh.read()
    except OSError:
        return ""


def strip_comments(text):
    """Remove C# comments before looking for values.

    Not optional here. Those files are heavily commented and the comments quote
    numbers: superseded gains appear as "the old k_p=0.05 / k_d=0.005", and Q
    has an earlier value left commented out above the live one. Matching those
    instead of the real assignment reported three differences that did not
    exist, which is worse than reporting none - a check that cries wolf stops
    being read.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def csharp(text, name):
    """Value of a C# field assignment, as written."""
    m = re.search(r"\b" + re.escape(name) + r"\s*=\s*([^;]+);", strip_comments(text))
    return m.group(1).strip() if m else None


def yaml_field(text, name):
    m = re.search(r"^\s*" + re.escape(name) + r":\s*(\S+)\s*$", text, re.M)
    return m.group(1) if m else None


def num(value):
    if value is None:
        return None
    m = re.match(r"^-?[0-9.]+", str(value).replace("f", ""))
    return float(m.group(0)) if m else None


def must_match(label, ours, theirs, tol=1e-6, note=""):
    """For facts about the hardware, where a difference is a fault."""
    if theirs is None:
        ok, detail = False, "NOT FOUND in the Unity source"
    elif isinstance(ours, str):
        ok = ours == theirs
        detail = "Unity %-12s here %s" % (theirs, ours)
    else:
        ok = ours is not None and abs(ours - theirs) <= tol
        detail = "Unity %-12s here %s" % (theirs, ours)
    print("  %s  %-32s %s%s" % ("PASS" if ok else "FAIL", label, detail,
                                ("   <-- " + note) if note and not ok else ""))
    if not ok:
        FAILED.append(label)


def report(label, ours, theirs, unit=""):
    """For tuning, where a difference is a choice and not a fault."""
    same = "" if ours is None or theirs is None else (
        "" if abs(float(ours) - float(theirs)) > 1e-6 else "  (same)")
    print("       %-30s Unity %-12s here %s%s"
          % (label, "%s%s" % (theirs, unit) if theirs is not None else "?",
             "%s%s" % (ours, unit), same))


def has(label, text, needle):
    ok = needle in text
    print("  %s  %s" % ("PASS" if ok else "FAIL", label))
    if not ok:
        FAILED.append(label)


p = ParameterStore()
constants = read(os.path.join(SCRIPTS, "Constants.cs"))
scene = read(os.path.join(UNITY, "MainScene.unity"))
camera = read(os.path.join(SCRIPTS, "UVCCamera", "UVCCameraPlugin.cs"))
sender = read(os.path.join(SCRIPTS, "ImageProcessingInstructionSender.cs"))
controller = read(os.path.join(SCRIPTS, "MachineController.cs"))
editor = read(os.path.join(SCRIPTS, "MachineControllerEditor.cs"))
pid = read(os.path.join(SCRIPTS, "PIDTiltController.cs"))
juggle = read(os.path.join(SCRIPTS, "OscillatingJuggling.cs"))

if not constants:
    print("Unity project not found next to this one - nothing to compare.")
    sys.exit(1)

# ---------------------------------------------------------------- asserted
print("The machine itself - a difference here is a fault, not a choice")
must_match("plate width (m)", machine.PLATE_WIDTH,
           num(csharp(constants, "PlateWidth")))
must_match("motor-to-joint offset Q (m)", machine.Q, num(csharp(constants, "Q")))
must_match("link L1 (m)", machine.L1, num(csharp(constants, "L1")))
must_match("link L2 (m)", machine.L2, num(csharp(constants, "L2")))
must_match("plate height at rest (m)", machine.HEIGHT_ORIGIN,
           num(csharp(constants, "HeightOrigin")))

want = "{" + ",".join(str(i) for i in machine.PAIRINGS[p.get("mac_motor_order")]) + "}"
must_match("arm pairing", want,
           (csharp(constants, "MotorWiringOrder") or "").replace(" ", "") or None,
           note="which motor each computed arm drives is wiring, not tuning")

print("\nThe camera - this host's optical model is fitted against these")
must_match("camera FOV (deg)", optics.FOV_DEGREES,
           num(csharp(constants, "CameraFOVInDegrees")), 1e-4)
must_match("ball radius (mm)", optics.BALL_RADIUS_MM,
           num(csharp(constants, "RadiusOfPingPongBall")), 1e-4)
must_match("camera to plate at rest (mm)", optics.CAMERA_TO_PLATE_AT_REST,
           num(csharp(constants, "BallHeightAtOrigin")), 1e-4)

# ----------------------------------------------------------------- reported
print("\nTuning - each host is set on its own, differences are expected")

report("working origin (mm)", p.get("mac_origin_offset"),
       num(yaml_field(scene, "_originHeightOffsetMm")))
report("level trim X (deg)", p.get("mac_trim_x"),
       num(csharp(constants, "LevelTrimXDegrees")))
report("level trim Y (deg)", p.get("mac_trim_y"),
       num(csharp(constants, "LevelTrimYDegrees")))
print()

# The gains are in different units and cannot be compared as written: this host
# works in degrees per PIXEL because its controller reads the camera frame,
# Unity in degrees per MILLIMETRE because FOVCalculations has already
# converted. Shown converted so the two are at least readable together.
scale = p.get("ctl_ref_radius") / optics.BALL_RADIUS_MM
print("       gains, this host converted to deg/mm at %.2f px/mm" % scale)
report("k_p (deg/mm)", round(p.get("pid_kp_x") * scale, 3),
       num(csharp(constants, "k_p")))
report("k_d (deg/mm)", round(p.get("pid_kd_x") * scale, 3),
       num(csharp(constants, "k_d")))
report("k_i (deg/mm)", round(p.get("pid_ki_x") * scale, 3),
       num(csharp(constants, "k_i")))
report("max tilt (deg)", p.get("ctl_max_tilt"),
       num(csharp(constants, "MaxTiltAngle")))
report("tilt rate limit (deg/s)", p.get("ctl_slew_rate"),
       num(csharp(constants, "MaxTiltRateDegreesPerSecond")))
report("balancing move time (s)", p.get("mod_balance_move_time"),
       num(yaml_field(scene, "_balancingMoveTime")))
print()

# Exposure and gain especially: the detectors want different images. This host
# gates on HSV saturation and wants the ball just below clipping; Unity traces
# red-minus-blue against an absolute threshold. Neither value is wrong for the
# other program, and neither should be copied across without measuring.
print("       camera, whose detectors want different images")
report("exposure", p.get("cam_exposure"), num(csharp(camera, "Exposure")))
report("gain", p.get("cam_gain"), num(csharp(camera, "Gain")))
report("saturation", p.get("cam_saturation"), num(csharp(camera, "Saturation")))
report("contrast", p.get("cam_contrast"), num(csharp(camera, "Contrast")))

if juggle:
    print()
    print("       oscillating juggle, Unity's port of this host's Juggling mode")
    for label, ours, name in (
            ("juggle low (mm)", p.get("mod_jug_low"), "LowMm"),
            ("juggle high (mm)", p.get("mod_jug_high"), "HighMm"),
            ("rise time (s)", p.get("mod_jug_rise_time"), "RiseTime"),
            ("top dwell (s)", p.get("mod_jug_top_dwell"), "TopDwellTime"),
            ("fall time (s)", p.get("mod_jug_fall_time"), "FallTime"),
            ("bottom dwell (s)", p.get("mod_jug_bottom_dwell"), "BottomDwellTime")):
        report(label, ours, num(csharp(juggle, name)))

    phases = sum(p.get(k) for k in ("mod_jug_rise_time", "mod_jug_top_dwell",
                                    "mod_jug_fall_time", "mod_jug_bottom_dwell"))
    ours_cycle = sum(max(p.get(k), 0.05) + 0.02
                     for k in ("mod_jug_rise_time", "mod_jug_top_dwell",
                               "mod_jug_fall_time", "mod_jug_bottom_dwell"))
    print("       cycle: here %.2fs, Unity batched %.2fs, Unity per-phase %.2fs"
          % (ours_cycle, phases + 0.05, phases + 4 * 0.05))

# ------------------------------------------------- Unity's own completeness
print("\nUnity features that have to be wired, not merely valued")
has("trim reaches the wire", controller, "Constants.LevelTrimXDegrees,")
has("trim applied at the one chokepoint", controller,
    "var originOffset = new HLMachineState(")
has("nudge buttons exist", editor, "NudgeLevelTrim")
has("reset button exists", editor, "ResetLevelTrim")
has("integral term used", pid, "Constants.k_i")
has("tilt rate limited", pid, "MaxTiltRateDegreesPerSecond")
has("integral reset when the ball is lost", sender,
    "PIDTiltController.Instance.Reset()")

print()
if FAILED:
    print("FAULTS (%d): %s" % (len(FAILED), ", ".join(FAILED)))
else:
    print("Both hosts agree about the hardware. Tuning differences above are")
    print("each host's own and are not faults.")
sys.exit(1 if FAILED else 0)
