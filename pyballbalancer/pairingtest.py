"""Which arms form the X pair and which the Y pair?

`machine.arm_angles` puts arms 0/1 on the X tilt and 2/3 on the Y tilt, and
assumes each pair spans OPPOSITE corners of the plate. If the physical motors
are connected so that a pair spans ADJACENT corners instead, both tilt commands
act on the same physical axis: the measured response directions come out 180
degrees apart rather than 90, and no amount of swapping or inverting can help,
because the machine has only one usable tilt axis.

Four arms split into two pairs exactly three ways, so this tries all of them.
Swapping the two members of a pair only flips that tilt's sign, which the
axis-mapping check already handles, so the pairing is the only real choice.

Two scores matter, and they disagree under a wrong pairing:

* **The angle** between the two response directions. 90 is what a working
  machine gives.
* **The size** of the response. The plate is over-constrained -- three degrees
  of freedom driven by four arms -- so a wrong pairing asks for a set of arm
  heights the plate cannot physically take. The arms then fight each other and
  the ball barely stirs. A pairing that moves the ball well is one the plate
  can actually adopt.

Changing the order is safe while the plate is level: at zero tilt all four arm
angles are identical, so the permutation is a no-op at that instant.

    python pairingtest.py

Ball on the plate, near the middle of the camera view, hands out of frame.
"""
from __future__ import annotations

import math
import sys
import time

from PyQt5.QtWidgets import QApplication

import machine
from gui import MainWindow

TILT_DEG = 1.5
RAMP = 0.15
WINDOW = 0.22
SETTLE = 1.0
MIN_SAMPLES = 8
RETRIES = 3

# the three distinct ways to split four arms into two pairs
ORDERS = [((0, 1, 2, 3), "0+1 / 2+3  (as shipped)"),
          ((0, 2, 1, 3), "0+2 / 1+3"),
          ((0, 3, 1, 2), "0+3 / 1+2")]

app = QApplication(sys.argv)
win = MainWindow()
win.show()


def wait(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.004)


def ball():
    s = win._state
    return None if s is None else (s.x, s.y)


def fit(samples):
    if len(samples) < MIN_SAMPLES:
        return None
    t0 = samples[0][0]
    ts = [s[0] - t0 for s in samples]
    mt = sum(ts) / len(ts)
    den = sum((t - mt) ** 2 for t in ts)
    if den < 1e-9:
        return None
    out = []
    for axis in (1, 2):
        mv = sum(s[axis] for s in samples) / len(samples)
        out.append(sum((t - mt) * (s[axis] - mv) for t, s in zip(ts, samples)) / den)
    return out[0], out[1]


def leg(height, xt, yt):
    win.serial.send_pose(height, 0.0, 0.0, 0.4)
    wait(SETTLE)
    win.serial.send_pose(height, xt, yt, RAMP)
    wait(RAMP)
    samples = []
    end = time.monotonic() + WINDOW
    while time.monotonic() < end:
        wait(0.012)
        b = ball()
        if b is not None:
            samples.append((time.monotonic(), b[0], b[1]))
    span = RAMP + WINDOW
    win.serial.send_pose(height, -xt, -yt, RAMP)
    wait(2 * span)
    win.serial.send_pose(height, xt, yt, RAMP)
    wait(span)
    win.serial.send_pose(height, 0.0, 0.0, 0.4)
    wait(0.6)
    return fit(samples)


def leg_retried(height, xt, yt):
    for _ in range(RETRIES):
        v = leg(height, xt, yt)
        if v is not None:
            return v
    return None


def response(height, axis):
    d = TILT_DEG
    plus = leg_retried(height, d if axis == "x" else 0.0, 0.0 if axis == "x" else d)
    minus = leg_retried(height, -d if axis == "x" else 0.0, 0.0 if axis == "x" else -d)
    if plus is None or minus is None:
        return None
    return ((plus[0] - minus[0]) / 2.0, (plus[1] - minus[1]) / 2.0)


wait(4.0)
if not win.serial.is_open:
    print("no serial link — close the GUI if it is still open")
    sys.exit(1)

height = win._origin_height() + win.params.get("mod_balance_height") / 1000.0
original = machine.MOTOR_ORDER
print("Testing three motor pairings at %.0f mm. About a minute."
      % win.params.get("mod_balance_height"))
print("The plate is levelled before each change, which makes the switch a no-op.\n")

win.serial.send_pose(height, 0.0, 0.0, win.params.get("mod_rise_time"))
wait(win.params.get("mod_rise_time") + 1.2)

results = []
for order, label in ORDERS:
    # level first: at zero tilt every arm angle is the same, so permuting
    # which arm goes to which motor changes nothing at this instant
    win.serial.send_pose(height, 0.0, 0.0, 0.5)
    wait(1.2)
    machine.MOTOR_ORDER = order
    print("  %-24s measuring..." % label)

    rx = response(height, "x")
    ry = response(height, "y") if rx is not None else None
    if rx is None or ry is None:
        print("     lost the ball; no reading for this pairing")
        results.append((label, order, None, None, None))
        continue

    mx, my = math.hypot(*rx), math.hypot(*ry)
    if mx < 1e-6 or my < 1e-6:
        results.append((label, order, None, None, None))
        continue
    ang = math.degrees(math.acos(max(-1.0, min(1.0,
          (rx[0] * ry[0] + rx[1] * ry[1]) / (mx * my)))))
    print("     angle %5.0f deg   response X %4.0f, Y %4.0f px/s" % (ang, mx, my))
    results.append((label, order, ang, mx, my))

machine.MOTOR_ORDER = original
win.serial.send_pose(height, 0.0, 0.0, 0.5)
wait(1.0)
win.machine_panel.go_origin()
wait(1.5)

print("\n%-26s %-10s %-12s %s" % ("pairing", "angle", "response", "verdict"))
best, best_score = None, -1.0
for label, order, ang, mx, my in results:
    if ang is None:
        print("%-26s %-10s %-12s no reading" % (label, "-", "-"))
        continue
    # perpendicular AND able to move the ball; a pairing the plate cannot
    # adopt scores badly on the second even if the angle looks plausible
    score = min(mx, my) * max(0.0, 1.0 - abs(ang - 90.0) / 90.0)
    verdict = "usable" if abs(ang - 90.0) < 30.0 else "axes not independent"
    print("%-26s %-10s %-12s %s"
          % (label, "%.0f deg" % ang, "%.0f px/s" % min(mx, my), verdict))
    if score > best_score:
        best, best_score = (label, order, ang), score

print()
measured = [r for r in results if r[2] is not None]
if not measured:
    # Distinct from a negative result, and must not be reported as one: no
    # pairing was rejected here, none was tried against a visible ball.
    print("No pairing was actually measured -- the ball was not in view for any")
    print("of them. This says nothing about the pairing. The run takes about a")
    print("minute, so put the ball back near the middle of the camera view and")
    print("try again; a temporary rim makes it far more likely to survive.")
elif best is None or abs(best[2] - 90.0) > 30.0:
    print("Of the %d pairing(s) that could be measured, none gave independent"
          % len(measured))
    print("tilt axes. If all three were measured that rules the pairing out,")
    print("and the collinearity lies in the linkage or the measurement instead.")
else:
    print("Best pairing: %s  (%.0f deg apart)" % (best[0], best[2]))
    print("To keep it, set MOTOR_ORDER in machine.py to %s" % (best[1],))

win.close()
wait(1.0)
