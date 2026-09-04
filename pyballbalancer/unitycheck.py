"""Does the Unity host carry the same tuning this one was tuned to?

The two programs drive the same machine through the same firmware and share
their kinematics exactly, so any difference in behaviour between them comes
down to their settings having drifted apart. That is easy to let happen and
hard to see: the values live in C# constants, in a serialized Unity scene, and
in this app's parameter table, and nothing forces the three to agree.

This reads all three and reports the differences. No hardware, no Unity, no
serial port.

    python unitycheck.py

Two things it is careful about, because both have broken this port silently:

  * The PD gains CANNOT be compared directly. This host works in degrees per
    PIXEL, because its controller reads the camera frame; Unity works in
    degrees per MILLIMETRE, because FOVCalculations has already converted.
    The conversion is the image scale at the height the gains were tuned at.
  * A [SerializeField] value stored in MainScene.unity OVERRIDES the C#
    default at runtime, so checking Constants.cs alone proves nothing about
    what the machine will actually do.
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

    Not optional here. This file is heavily commented and the comments quote
    numbers: the superseded gains appear as "the old k_p=0.05 / k_d=0.005",
    and Q has an earlier value left commented out above the live one. Matching
    those instead of the real assignment reported three differences that did
    not exist, which is worse than reporting none - a check that cries wolf
    stops being read.
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


def check(label, ours, theirs, tol=1e-6, note=""):
    if theirs is None:
        ok, detail = False, "NOT FOUND in the Unity source"
    elif isinstance(ours, str):
        ok = ours == theirs
        detail = "Unity %-12s PyQt %s" % (theirs, ours)
    else:
        ok = ours is not None and abs(ours - theirs) <= tol
        detail = "Unity %-12s PyQt %s" % (theirs, ours)
    print("  %s  %-34s %s%s" % ("PASS" if ok else "FAIL", label, detail,
                                ("   <-- " + note) if note and not ok else ""))
    if not ok:
        FAILED.append(label)


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

if not constants:
    print("Unity project not found next to this one - nothing to compare.")
    sys.exit(1)

print("Geometry - must match exactly, or the two hosts command different poses")
check("plate width (m)", machine.PLATE_WIDTH, num(csharp(constants, "PlateWidth")))
check("motor-to-joint offset Q (m)", machine.Q, num(csharp(constants, "Q")))
check("link L1 (m)", machine.L1, num(csharp(constants, "L1")))
check("link L2 (m)", machine.L2, num(csharp(constants, "L2")))
check("plate height at rest (m)", machine.HEIGHT_ORIGIN,
      num(csharp(constants, "HeightOrigin")))

print("\nMachine")
want = "{" + ",".join(str(i) for i in machine.PAIRINGS[p.get("mac_motor_order")]) + "}"
got = csharp(constants, "MotorWiringOrder")
check("arm pairing", want, (got or "").replace(" ", "") or None,
      note="PyQt pairing is " + p.get("mac_motor_order"))
check("level trim X (deg)", p.get("mac_trim_x"),
      num(csharp(constants, "LevelTrimXDegrees")), 1e-4)
check("level trim Y (deg)", p.get("mac_trim_y"),
      num(csharp(constants, "LevelTrimYDegrees")), 1e-4)

# The one that hides: Constants.cs is only the fallback. MachineController.Awake()
# overwrites it from a [SerializeField] the scene has already stored.
check("working origin, Constants.cs (m)", p.get("mac_origin_offset") / 1000.0,
      num(csharp(constants, "OriginHeightOffset")), 1e-9)
check("working origin, MainScene (mm)", p.get("mac_origin_offset"),
      num(yaml_field(scene, "_originHeightOffsetMm")), 1e-6,
      note="the SCENE value is what runs")

print("\nControl")
scale = p.get("ctl_ref_radius") / optics.BALL_RADIUS_MM
print("  gains converted at %.3f px/mm - a %.0f mm ball radius reading %.0f px"
      % (scale, optics.BALL_RADIUS_MM, p.get("ctl_ref_radius")))
check("k_p (deg/mm)", round(p.get("pid_kp_x") * scale, 3),
      num(csharp(constants, "k_p")), 5e-3)
check("k_d (deg/mm)", round(p.get("pid_kd_x") * scale, 3),
      num(csharp(constants, "k_d")), 5e-3)
check("k_i (deg/mm)", round(p.get("pid_ki_x") * scale, 3),
      num(csharp(constants, "k_i")), 5e-3)
check("integral clamp (deg)", p.get("pid_i_clamp"),
      num(csharp(constants, "IntegralClampDegrees")))
check("max tilt (deg)", p.get("ctl_max_tilt"),
      num(csharp(constants, "MaxTiltAngle")))
check("min tilt (deg)", -p.get("ctl_max_tilt"),
      num(csharp(constants, "MinTiltAngle")))
check("tilt rate limit (deg/s)", p.get("ctl_slew_rate"),
      num(csharp(constants, "MaxTiltRateDegreesPerSecond")))
check("balancing move time, scene (s)", p.get("mod_balance_move_time"),
      num(yaml_field(scene, "_balancingMoveTime")), 1e-6,
      note="the SCENE value is what runs")

# Exposure and gain are deliberately NOT compared. The two hosts run different
# detectors and want different images: this one gates on HSV and wants the ball
# just below clipping so it keeps its saturation, while Unity's imgMode 7 traces
# a red-minus-blue "custom gray" and keeps whatever exceeds Constants.Threshold,
# so it wants the ball bright. Copying -8/120 into Unity stopped its tracer
# finding any cluster at all and the machine sat armed with no ball. Reported
# side by side so the difference is visible, never asserted equal.
print("\nCamera - exposure and gain are NOT shared, the detectors differ")
print("       this host  exposure %-5s gain %-5s (HSV gate, avoid clipping)"
      % (p.get("cam_exposure"), p.get("cam_gain")))
print("       Unity      exposure %-5s gain %-5s (r-b tracer, wants brightness)"
      % (num(csharp(camera, "Exposure")), num(csharp(camera, "Gain"))))
check("saturation", p.get("cam_saturation"), num(csharp(camera, "Saturation")))
check("contrast", p.get("cam_contrast"), num(csharp(camera, "Contrast")))

print("\nOptics - this host's camera model is fitted against Unity's constants")
check("camera FOV (deg)", optics.FOV_DEGREES,
      num(csharp(constants, "CameraFOVInDegrees")), 1e-4)
check("ball radius (mm)", optics.BALL_RADIUS_MM,
      num(csharp(constants, "RadiusOfPingPongBall")), 1e-4)
check("camera to plate at rest (mm)", optics.CAMERA_TO_PLATE_AT_REST,
      num(csharp(constants, "BallHeightAtOrigin")), 1e-4)

print("\nFeatures that have to be wired, not merely valued")
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
    print("DIFFERENCES (%d): %s" % (len(FAILED), ", ".join(FAILED)))
    print()
    print("Anything flagged 'the SCENE value is what runs' cannot be fixed by")
    print("editing Constants.cs - change it in MainScene.unity, or in the")
    print("MachineController inspector and save the scene.")
else:
    print("Unity carries the same tuning as this host.")
sys.exit(1 if FAILED else 0)
