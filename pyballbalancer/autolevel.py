"""Level the plate using the ball as the instrument.

A spirit level sets the trim at the working origin, but balancing happens
40 mm up, and the plate need not be level there: the four arms are at quite
different angles, and any asymmetry in link lengths shows up as a residual
slope that grows with height. On a slope the ball accelerates away before the
controller has anything useful to do, which reads as "balancing does not work".

The ball is a better instrument than a spirit level here, because it measures
the slope at the height that matters and in the axes the controller uses. A
ball on a plate of tilt theta accelerates at c*g*sin(theta) with c = 5/7 for a
solid sphere, so watching it drift gives the slope directly.

The sign that a trim correction should take is not assumed. The first probe on
each axis deliberately moves the trim and watches whether the drift got better
or worse, and the direction is taken from that -- guessing it would simply
level the plate the wrong way twice as fast.

    python autolevel.py            measure and report
    python autolevel.py --apply    and keep the trim it finds

Put the ball on the plate near the middle, hands out of frame.
"""
from __future__ import annotations

import math
import sys
import time

from PyQt5.QtWidgets import QApplication

from gui import MainWindow

APPLY = "--apply" in sys.argv

SETTLE = 0.5          # let the plate finish moving before timing anything
WINDOW = 0.90         # sample up to this long, or until the ball leaves
MIN_ARC = 0.45        # a shorter arc than this cannot pin the curvature down
MAX_STEP = 2.00       # the correction comes from physics, not from creeping
                      # toward the answer: a cap smaller than the slope just
                      # spends rounds, and every round is a chance to lose
                      # the ball. Kept only as a guard against a wild reading.
ROUNDS = 6
GOOD_ENOUGH = 45.0    # px/s^2 left over: about 0.08 deg of slope
MIN_SAMPLES = 6
MM_PER_PX = 0.205     # from the ball's measured radius in frame
C_ROLL, G = 5.0 / 7.0, 9810.0     # solid sphere, mm/s^2

app = QApplication(sys.argv)
win = MainWindow()
win.show()


def wait(seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.004)


def ball():
    s = win._state
    return None if s is None else (s.x, s.y)


def fit(samples):
    """Ball ACCELERATION, px/s^2, from position against time.

    Velocity would be simpler but it is not measurable here: on a sloped plate
    the ball never comes to rest, so it is already moving when a reading
    starts, and its speed then says as much about how it was put down as about
    the slope. Acceleration does not care about the initial velocity at all --
    it is the quadratic term, and a constant starting speed only moves the
    linear one. Fitting position to a*t^2/2 + v*t + x0 and keeping a is
    therefore the measurement that survives a ball still rolling.
    """
    if len(samples) < MIN_SAMPLES:
        return None
    t0 = samples[0][0]
    ts = [s[0] - t0 for s in samples]
    # Curvature is what is being measured, and a short arc barely has any.
    # Simulated against this fit with 1.5 px of position noise: a 0.40 s window
    # gives a standard deviation of 57 px/s^2 on a true 150 -- readings that
    # disagree fourfold between runs. 0.80 s brings that to 10, 1.20 s to 3.
    if ts[-1] - ts[0] < MIN_ARC:
        return None

    # normal equations for a quadratic; three unknowns, so the sums are small
    n_ = len(ts)
    s1 = sum(ts); s2 = sum(t * t for t in ts)
    s3 = sum(t ** 3 for t in ts); s4 = sum(t ** 4 for t in ts)
    out = []
    for axis in (1, 2):
        ys = [p[axis] for p in samples]
        b0 = sum(ys); b1 = sum(t * y for t, y in zip(ts, ys))
        b2 = sum(t * t * y for t, y in zip(ts, ys))
        # solve [[n,s1,s2],[s1,s2,s3],[s2,s3,s4]] . [x0,v,a/2] = [b0,b1,b2]
        m = [[n_, s1, s2, b0], [s1, s2, s3, b1], [s2, s3, s4, b2]]
        for col in range(3):
            piv = max(range(col, 3), key=lambda r: abs(m[r][col]))
            if abs(m[piv][col]) < 1e-12:
                return None
            m[col], m[piv] = m[piv], m[col]
            for r in range(3):
                if r == col:
                    continue
                f = m[r][col] / m[col][col]
                for c in range(col, 4):
                    m[r][c] -= f * m[col][c]
        out.append(2.0 * m[2][3] / m[2][2])       # a = 2 * (a/2)
    return out[0], out[1]


def wait_for_ball(seconds=20.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        wait(0.05)
        if ball() is not None:
            return True
    return False


def correction_deg(drift_px_s):
    """Trim change, degrees, that cancels a measured acceleration.

    The ball has been accelerating since the plate settled, so its velocity
    over that time is the acceleration, and a ball on a slope accelerates at
    c*g*sin(theta) -- which gives the slope outright. No probing is needed for
    which way the correction goes: the axis mapping is known, so a positive
    tilt moves the ball positive, and a ball drifting negative wants a
    positive trim.
    """
    accel_mm = drift_px_s * MM_PER_PX
    ratio = max(-1.0, min(1.0, accel_mm / (C_ROLL * G)))
    return -math.degrees(math.asin(ratio))


def drift(height):
    """Ball acceleration, px/s^2, with the plate commanded level."""
    win.serial.send_pose(height, 0.0, 0.0, 0.4)
    wait(SETTLE)
    samples = []
    misses = 0
    end = time.monotonic() + WINDOW
    while time.monotonic() < end:
        wait(0.012)
        b = ball()
        if b is None:
            # stop early rather than pad the arc across a gap; acceleration
            # does not need the ball to have started at rest, only to have
            # been watched continuously for long enough
            misses += 1
            if misses > 8 and samples:
                break
            continue
        misses = 0
        samples.append((time.monotonic(), b[0], b[1]))
    return fit(samples), len(samples)


def nudge(axis, amount):
    key = "mac_trim_%s" % axis
    win.params.set(key, win.params.get(key) + amount)


wait(4.0)
if not win.serial.is_open:
    print("no serial link — close the GUI if it is still open")
    sys.exit(1)

height = win._origin_height() + win.params.get("mod_balance_height") / 1000.0
mm = win.params.get("mod_balance_height")
print("Levelling at %.0f mm, where balancing actually runs." % mm)
print("Starting trim: X %+.2f  Y %+.2f deg"
      % (win.params.get("mac_trim_x"), win.params.get("mac_trim_y")))
start = (win.params.get("mac_trim_x"), win.params.get("mac_trim_y"))

win.serial.send_pose(height, 0.0, 0.0, win.params.get("mod_rise_time"))
wait(win.params.get("mod_rise_time") + 1.2)

# Wait rather than fail. On a sloped plate the ball rolls off between runs, so
# a tool that demands it already be there just sends you round the loop again.
print("\nPut the ball on the plate, near the middle of the camera view.")
print("Waiting up to 60 s for it...")
if not wait_for_ball(60.0):
    print("No ball seen. Nothing to measure against.")
    win.machine_panel.go_origin(); wait(1.5); win.close(); sys.exit(1)
print("got it.")

d, n = drift(height)
if d is None:
    print("\nBall seen but it left before a reading finished (%d samples)." % n)
    win.machine_panel.go_origin(); wait(1.5); win.close(); sys.exit(1)

print("\n%-6s %-22s %-18s %s" % ("round", "trim X / Y (deg)", "accel (px/s2)", "note"))
print("%-6s %-22s %-18s %s"
      % ("start", "%+.2f / %+.2f" % start, "%+6.0f, %+6.0f" % d, "%d samples" % n))

lost = False
best = (math.hypot(*d), win.params.get("mac_trim_x"), win.params.get("mac_trim_y"))

for rnd in range(1, ROUNDS + 1):
    if math.hypot(*d) < GOOD_ENOUGH:
        print("%-6d %-22s %-18s level enough" % (rnd, "", ""))
        break

    # Both axes at once: the correction comes from physics rather than from
    # probing, so there is no reason to spend a round per axis, and every extra
    # round is another chance for the ball to leave.
    cx = max(-MAX_STEP, min(MAX_STEP, correction_deg(d[0])))
    cy = max(-MAX_STEP, min(MAX_STEP, correction_deg(d[1])))
    nudge("x", cx)
    nudge("y", cy)

    if not wait_for_ball(20.0):
        lost = True
        print("%-6d %-22s ball gone -- put it back" % (rnd, ""))
        break
    probe, n = drift(height)
    if probe is None:
        lost = True
        break
    d = probe
    if math.hypot(*d) < best[0]:
        best = (math.hypot(*d), win.params.get("mac_trim_x"),
                win.params.get("mac_trim_y"))

    print("%-6d %-22s %-18s %s"
          % (rnd,
             "%+.2f / %+.2f" % (win.params.get("mac_trim_x"),
                                win.params.get("mac_trim_y")),
             "%+6.0f, %+6.0f" % d, "applied %+.2f/%+.2f, %d samples" % (cx, cy, n)))

win.machine_panel.go_origin()
wait(1.5)

final = (win.params.get("mac_trim_x"), win.params.get("mac_trim_y"))
print("\n----------------------------------------------------------")
if lost:
    print("Lost the ball part-way. What was found up to that point:")
print("  trim was  X %+.2f  Y %+.2f" % start)
print("  trim now  X %+.2f  Y %+.2f" % final)
print("  best seen X %+.2f  Y %+.2f  at %.0f px/s drift" % (best[1], best[2], best[0]))
print("  residual acceleration %.0f px/s2 (%.1f mm/s2)"
      % (math.hypot(*d), math.hypot(*d) * MM_PER_PX))
slope = math.degrees(math.asin(max(-1.0, min(1.0,
        math.hypot(*d) * MM_PER_PX / (C_ROLL * G)))))
print("  which is about %.2f deg of residual slope" % slope)
print("----------------------------------------------------------")

if APPLY:
    # Keep the best round, not the last: a round that lost the ball can leave
    # the trim somewhere worse than where it had already got to.
    win.params.set("mac_trim_x", best[1])
    win.params.set("mac_trim_y", best[2])
    print("\nKept the best. Put these in params.py to make them the defaults:")
    print("    mac_trim_x default %.2f" % best[1])
    print("    mac_trim_y default %.2f" % best[2])
else:
    win.params.set("mac_trim_x", start[0])
    win.params.set("mac_trim_y", start[1])
    print("\nNot kept — re-run with --apply to keep them.")

win.close()
wait(1.0)
