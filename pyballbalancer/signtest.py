"""Which way does the plate actually push the ball?

If a commanded tilt moves the ball the wrong way, the loop accelerates it
outward instead of catching it, and the ball leaves the plate every time. That
looks identical to gains being wrong, or to the plate being too aggressive, so
it has to be measured rather than guessed — there are eight combinations of
swap/invert and trying them by hand costs a ball roll each.

The measurement, and why it is shaped like this:

* **Velocity, not position.** Under a constant tilt the ball accelerates, so
  where it *is* after a fixed time depends on where it started. How fast it is
  moving does not.
* **Both directions, then differenced.** A plate that is slightly off level, or
  a ball already drifting, adds the same bias to the + and - legs. Subtracting
  them cancels it; a single leg would measure the bias as much as the response.
* **Small tilt, short window.** There is no rim on this plate. The budget is a
  centimetre or so of travel, not a free roll.

    python signtest.py            measure and report
    python signtest.py --apply    also write the result into the parameters

Put the ball on the plate near the centre first, and keep hands out of frame.
"""
from __future__ import annotations

import math
import sys
import time

from PyQt5.QtWidgets import QApplication

from gui import MainWindow

APPLY = "--apply" in sys.argv

TILT_DEG = 1.5        # enough to move the ball, gentle enough to keep it
RAMP = 0.15           # let the plate reach the tilt before timing anything
WINDOW = 0.22         # drift is timed over this: ~12 mm of travel per leg
SETTLE = 1.2          # quiet time at level between legs
MIN_SAMPLES = 8       # a leg thinner than this is noise, not a measurement
RETRIES = 3           # a thin leg is retried rather than believed

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


def hold(height, xt, yt, move_time):
    win.serial.send_pose(height, xt, yt, move_time)


def wait_for_ball(seconds=15.0):
    """Refuse to start without a ball, rather than measuring noise."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        wait(0.1)
        b = ball()
        if b is not None:
            return b
        why = win.camera._vision.rejections
        if why:
            print("   waiting... %s" % why[0][:70])
    return None


def fit_velocity(samples):
    """Least-squares slope through whatever samples arrived.

    Reading the position at two instants needs both of those instants to have
    a detection, and detection here is intermittent — one missed frame then
    loses the whole leg, which reads as "the ball rolled off" when the ball
    never moved. Fitting a line uses every sample that did arrive and degrades
    gracefully as they thin out.
    """
    if len(samples) < MIN_SAMPLES:
        return None
    t0 = samples[0][0]
    ts = [s[0] - t0 for s in samples]
    mean_t = sum(ts) / len(ts)
    denom = sum((t - mean_t) ** 2 for t in ts)
    if denom < 1e-9:
        return None
    out = []
    for axis in (1, 2):
        mean_v = sum(s[axis] for s in samples) / len(samples)
        out.append(sum((t - mean_t) * (s[axis] - mean_v)
                       for t, s in zip(ts, samples)) / denom)
    return out[0], out[1]


def leg(height, xt, yt):
    """Ball velocity, px/s, while one tilt is held. None if it could not be got."""
    hold(height, 0.0, 0.0, 0.4)
    wait(SETTLE)
    hold(height, xt, yt, RAMP)
    wait(RAMP)

    samples, seen, total = [], 0, 0
    end = time.monotonic() + WINDOW
    while time.monotonic() < end:
        wait(0.012)
        total += 1
        b = ball()
        if b is not None:
            seen += 1
            samples.append((time.monotonic(), b[0], b[1]))

    # Unwind as a symmetric three-leg profile: +d for T, -d for 2T, +d for T.
    # Under constant tilt the ball accelerates, so the obvious two-leg unwind
    # (-d for twice as long, then level) ends with the ball at its top speed
    # and the plate suddenly flat -- no tilt left to stop it, and it rolls
    # away. Three legs bring it back to where it started with zero velocity,
    # which is what lets leg after leg run without re-placing the ball.
    span = RAMP + WINDOW
    hold(height, -xt, -yt, RAMP)
    wait(2 * span)
    hold(height, xt, yt, RAMP)
    wait(span)
    hold(height, 0.0, 0.0, 0.4)
    wait(0.6)

    v = fit_velocity(samples)
    if seen < MIN_SAMPLES:
        why = win.camera._vision.rejections
        last = (" [%s]" % why[0][:58]) if why else ""
        if samples:
            last += "  last seen at (%+.0f, %+.0f) px" % (samples[-1][1], samples[-1][2])
    else:
        last = ""
    print("     tilt %+.1f,%+.1f: %d of %d frames detected%s%s"
          % (xt, yt, seen, total,
             "" if v else "  -- too thin to fit, retrying", last))
    return v


def leg_retried(height, xt, yt):
    """A leg, retried while it comes back too thin to mean anything.

    Differencing two legs is only as good as the worse of them: one built from
    a handful of scattered samples does not average out, it moves the answer
    somewhere arbitrary. Better to spend the time again than to report a
    mapping derived from it.
    """
    for _attempt in range(RETRIES):
        v = leg(height, xt, yt)
        if v is not None:
            return v
    return None


def response(height, axis):
    """Ball response to a tilt on one axis, with the bias differenced out."""
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

# start from the identity mapping, or we would be measuring the mapping
# already in force rather than the machine underneath it
for key in ("ctl_swap_axes", "ctl_invert_x", "ctl_invert_y"):
    win.params.set(key, False)

height = win._origin_height() + win.params.get("mod_balance_height") / 1000.0
print("Rising to %.0f mm. Place the ball near the middle of the plate."
      % (win.params.get("mod_balance_height")))
hold(height, 0.0, 0.0, win.params.get("mod_rise_time"))
wait(win.params.get("mod_rise_time") + 1.0)

if wait_for_ball() is None:
    print("\nNo ball detected. Nothing can be measured without one -- put it on")
    print("the plate, keep hands out of frame, and run this again.")
    win.machine_panel.go_origin(); wait(1.5); win.close(); sys.exit(1)

print("ball found. Checking detection is steady before starting...")
steady, tries = 0, 0
while steady < 25 and tries < 500:
    wait(0.012)
    tries += 1
    steady = steady + 1 if ball() is not None else 0
if steady < 25:
    print("   not steady enough to measure against (best unbroken run: %d frames)."
          % steady)
    print("   Fix detection first -- the Session readout names the reason now.")
    win.machine_panel.go_origin()
    wait(1.5)
    win.close()
    sys.exit(1)
print("   steady. Measuring, about 20 s -- it will tilt four times.\n")

rx = response(height, "x")
if rx is None:
    print("lost the ball during the X legs.")
ry = response(height, "y") if rx is not None else None
if rx is not None and ry is None:
    print("lost the ball during the Y legs.")

win.machine_panel.go_origin()
wait(1.5)

if rx is not None and ry is None:
    # Half an answer is still worth having: it halves the guesswork.
    print("\nThe X axis did measure: a +X tilt moved the ball (%+.0f, %+.0f) px/s."
          % rx)
    if abs(rx[0]) >= abs(rx[1]):
        print("That is mostly along the camera's x, so the axes are NOT swapped,")
        print("and X %s be inverted." % ("must" if rx[0] < 0 else "need not"))
    else:
        print("That is mostly along the camera's y, so the axes ARE swapped.")

if rx is None or ry is None:
    print("\nThe ball has to stay in view for the whole measurement. With no rim")
    print("on the plate that is hard: a cardboard collar or a tape lip around")
    print("the edge makes this and every later tuning step possible.")
    win.close(); wait(0.8)
    sys.exit(1)

print("response to a +X tilt: (%+7.1f, %+7.1f) px/s" % rx)
print("response to a +Y tilt: (%+7.1f, %+7.1f) px/s" % ry)

mag_x, mag_y = math.hypot(*rx), math.hypot(*ry)
print("magnitudes: X %.0f px/s, Y %.0f px/s" % (mag_x, mag_y))

ratio = max(mag_x, mag_y) / max(1e-6, min(mag_x, mag_y))
if ratio > 3.0:
    print("\nThe two axes responded %.1f times differently. On a machine that is"
          % ratio)
    print("symmetric by construction that is not a real difference: one leg was")
    print("measured against a ball that was already moving, or detection thinned")
    print("out. Not reporting a mapping derived from it -- run it again.")
    win.close()
    wait(0.8)
    sys.exit(1)

if mag_x < 20.0 or mag_y < 20.0:
    print("\nToo small to trust. Either the tilt is not reaching the plate or the")
    print("ball is stuck; check the Machine tab tilt buttons move it by hand.")
    win.close(); wait(0.8)
    sys.exit(1)

# how far apart the two response directions are: they must be perpendicular,
# or no combination of swap and invert can describe the mapping
angle = math.degrees(math.acos(max(-1.0, min(1.0,
        (rx[0] * ry[0] + rx[1] * ry[1]) / (mag_x * mag_y)))))
print("angle between them: %.0f deg (should be near 90)" % angle)

swap = abs(rx[1]) > abs(rx[0])
if swap:
    eff_x, eff_y = rx[1], ry[0]
else:
    eff_x, eff_y = rx[0], ry[1]
# The controller drives a positive error negative, so for the plate to push the
# ball back, a +tilt must move it in the +direction. A negative response there
# means that axis has to be inverted.
inv_x = eff_x < 0
inv_y = eff_y < 0

print("\n--------------------------------------------------------------")
print("  swap axes : %s" % swap)
print("  invert X  : %s" % inv_x)
print("  invert Y  : %s" % inv_y)
print("--------------------------------------------------------------")
if abs(angle - 90.0) > 30.0:
    print("WARNING: the two axes are %.0f deg apart, not perpendicular." % angle)
    print("No swap/invert can fix that -- it means the two tilt commands are")
    print("acting on nearly the same physical direction. Suspect the motor")
    print("pairing (machine.MOTOR_ORDER) before trusting the settings above.")

if APPLY:
    win.params.set("ctl_swap_axes", swap)
    win.params.set("ctl_invert_x", inv_x)
    win.params.set("ctl_invert_y", inv_y)
    print("\nApplied to the running parameters. Save a preset to keep them.")
else:
    print("\nRe-run with --apply to write these into the parameters,")
    print("or set them by hand on the Control tab.")

win.close()
wait(1.0)
