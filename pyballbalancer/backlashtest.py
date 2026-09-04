"""How much tilt does the plate ignore before it moves?

A ball that never quite comes to rest is usually not a tuning problem. If the
arms have play, a small commanded tilt does nothing at all until that play is
taken up, and then the plate moves suddenly. The loop therefore cannot make
small corrections: it asks, nothing happens, the error grows, and eventually
the plate lurches. The result is a ball that keeps drifting and being caught,
for ever, at an amplitude no gain change will reduce.

This measures the size of that dead zone, using the ball as the instrument.
From level, the tilt is raised a step at a time and the ball watched; the tilt
at which it finally starts to move is the play plus whatever static friction
the ball has. Doing it in both directions gives the whole dead band.

    python backlashtest.py

Ball on the plate near the middle, hands out of frame.
"""
from __future__ import annotations

import math
import sys
import time

from PyQt5.QtWidgets import QApplication

from gui import MainWindow

STEP = 0.10           # degrees added per step
MAX_TILT = 2.5        # give up beyond this
DWELL = 0.70          # how long to hold each step before judging
MOVED_MM_S = 12.0     # ball speed that counts as "it moved"
SETTLE = 2.0

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


def wait_for_ball(seconds=40.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        wait(0.05)
        if ball() is not None:
            return True
    return False


def speed_mm_s(height, xt, yt, mm_per_px):
    """Hold a tilt and measure how fast the ball is travelling."""
    win.serial.send_pose(height, xt, yt, 0.25)
    wait(DWELL)
    pts = []
    end = time.monotonic() + 0.35
    while time.monotonic() < end:
        wait(0.012)
        b = ball()
        if b is not None:
            pts.append((time.monotonic(), b[0], b[1]))
    if len(pts) < 6:
        return None
    t0 = pts[0][0]
    ts = [p[0] - t0 for p in pts]
    mt = sum(ts) / len(ts)
    den = sum((t - mt) ** 2 for t in ts)
    if den < 1e-9:
        return None
    out = []
    for axis in (1, 2):
        mv = sum(p[axis] for p in pts) / len(pts)
        out.append(sum((t - mt) * (p[axis] - mv) for t, p in zip(ts, pts)) / den)
    return math.hypot(*out) * mm_per_px


def threshold(height, axis, sign, mm_per_px):
    """Smallest tilt in this direction that actually moves the ball."""
    win.serial.send_pose(height, 0.0, 0.0, 0.4)
    wait(SETTLE)
    steps = int(MAX_TILT / STEP)
    for i in range(1, steps + 1):
        d = sign * STEP * i
        xt, yt = (d, 0.0) if axis == "x" else (0.0, d)
        sp = speed_mm_s(height, xt, yt, mm_per_px)
        if sp is None:
            return None, "lost the ball"
        if sp > MOVED_MM_S:
            return abs(d), "%.0f mm/s" % sp
    return None, "no movement even at %.1f deg" % MAX_TILT


wait(4.0)
if not win.serial.is_open:
    print("no serial link — close the GUI first")
    sys.exit(1)

height = win._origin_height() + win.params.get("mod_balance_height") / 1000.0
win.serial.send_pose(height, 0.0, 0.0, win.params.get("mod_rise_time"))
wait(win.params.get("mod_rise_time") + 1.2)

print("Put the ball on the plate, near the middle. Waiting...")
if not wait_for_ball():
    print("no ball; nothing to measure against")
    win.machine_panel.go_origin(); wait(1.5); win.close(); sys.exit(1)

s = win._state
mm_per_px = 40.0 / (2.0 * s.radius) if s and s.radius > 5 else 0.20
print("ball radius %.0f px, so %.3f mm per px" % (s.radius if s else 0, mm_per_px))
print("Stepping the tilt up in %.2f deg steps until the ball moves.\n" % STEP)

results = {}
for axis in ("x", "y"):
    for sign, name in ((+1, "+"), (-1, "-")):
        if not wait_for_ball(20.0):
            print("  %s%s : ball gone, put it back" % (axis.upper(), name))
            continue
        val, note = threshold(height, axis, sign, mm_per_px)
        results["%s%s" % (axis.upper(), name)] = val
        print("  %s%s : %s   (%s)"
              % (axis.upper(), name,
                 "moves at %.2f deg" % val if val else "never moved", note))

win.serial.send_pose(height, 0.0, 0.0, 0.4)
wait(1.0)
win.machine_panel.go_origin()
wait(1.5)

# The two directions on an axis say different things. On a level plate with
# play, both need the same tilt. A slope adds to one and subtracts from the
# other, so the DIFFERENCE is the slope and the AVERAGE is the dead zone --
# two separate faults, only one of which is fixable in software.
print()
for axis in ("X", "Y"):
    pos, neg = results.get(axis + "+"), results.get(axis + "-")
    if pos is None or neg is None:
        print("%s: only one direction measured, cannot separate slope from play"
              % axis)
        continue
    slope = (pos - neg) / 2.0
    play = (pos + neg) / 2.0
    print("%s: slope %+.2f deg, dead zone %.2f deg" % (axis, slope, play))
    key = "mac_trim_%s" % axis.lower()
    # Sign checked on the machine, not assumed: raising trim X by 0.50 raised
    # the +X threshold from 1.10 to 1.80, so the correction SUBTRACTS.
    print("   to cancel the slope, set %s to %+.2f (currently %+.2f)"
          % (key, win.params.get(key) - slope, win.params.get(key)))
    print("   -- but re-measure after changing it; a run that loses the ball in")
    print("      either direction cannot separate slope from play at all")

vals = [v for v in results.values() if v]
if len(vals) < 2:
    print("\nNot enough readings to judge. A rim round the plate makes this easy.")
else:
    print("dead zone: %.2f to %.2f deg, mean %.2f"
          % (min(vals), max(vals), sum(vals) / len(vals)))
    mean = sum(vals) / len(vals)
    if mean < 0.15:
        print("That is small. The residual motion is not mechanical play, so")
        print("look at the gains and the loop delay instead.")
    else:
        print("That is a real dead zone. The controller cannot make a correction")
        print("smaller than it, so the ball will always drift that far before")
        print("anything happens - simulated, %.1f deg of play leaves the ball" % mean)
        print("moving at roughly %.0f mm/s, which no gain change removes."
              % (mean * 55))
        print()
        print("Worth checking the arm grub screws and the D-shaft bores before")
        print("tuning further; software can compensate but cannot invent stiffness.")

win.close()
wait(0.8)
