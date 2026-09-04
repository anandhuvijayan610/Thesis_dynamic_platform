"""Find the axis mapping by seeing which one actually balances.

The open-loop measurement in signtest.py wants the ball to survive four timed
tilts, and on a plate with a residual slope it rarely does. This asks a blunter
question instead: run the real controller under each candidate mapping and see
which keeps the ball. That needs no clean tilt response, tolerates a plate that
is not quite level -- a correctly signed loop simply holds a small standing
offset against the slope -- and scores the thing we actually care about.

There are eight combinations of swap/invert-X/invert-Y. A wrongly signed loop
drives the ball outward, so it loses it in about a second; a correct one keeps
it near the middle. The difference is not subtle, which is why this works where
careful open-loop timing does not.

    python mappingsearch.py            try them and report
    python mappingsearch.py --apply    and keep the winner

The ball will roll off under the wrong mappings. Put it back when asked; the
run waits for it. A rim round the plate makes this much quicker.
"""
from __future__ import annotations

import itertools
import math
import sys
import time

from PyQt5.QtWidgets import QApplication

from gui import MainWindow

APPLY = "--apply" in sys.argv

TRIAL = 5.0           # seconds of closed-loop per mapping
GOOD_RADIUS = 120.0   # px: "still near the middle"
WAIT_BALL = 25.0      # how long to wait for the ball to be put back

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


def wait_for_ball(seconds=WAIT_BALL):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        wait(0.05)
        if ball() is not None:
            # let it settle so the trial does not start mid-roll
            steady = 0
            while steady < 12 and time.monotonic() < end:
                wait(0.02)
                steady = steady + 1 if ball() is not None else 0
            if steady >= 12:
                return True
    return False


def trial(height, swap, inv_x, inv_y):
    """Run the real loop with one mapping. Returns (held_s, mean_px, n)."""
    win.params.set("ctl_swap_axes", swap)
    win.params.set("ctl_invert_x", inv_x)
    win.params.set("ctl_invert_y", inv_y)

    win.serial.send_pose(height, 0.0, 0.0, 0.5)
    wait(1.0)
    if not wait_for_ball(6.0):
        return None

    win.camera.reset_tracking()
    wait(0.3)
    win.modes.start("Balancing")
    win._armed = True
    win.control.set_enabled(True)

    started = time.monotonic()
    dists, held = [], 0.0
    while time.monotonic() - started < TRIAL:
        wait(0.02)
        b = ball()
        if b is None:
            continue
        d = math.hypot(*b)
        dists.append(d)
        if d < GOOD_RADIUS:
            held = time.monotonic() - started

    win.control.set_enabled(False)
    win._armed = False
    win.modes.stop()
    win.serial.send_pose(height, 0.0, 0.0, 0.5)
    wait(0.8)
    if not dists:
        return None
    return held, sum(dists) / len(dists), len(dists)


wait(4.0)
if not win.serial.is_open:
    print("no serial link — close the GUI if it is still open")
    sys.exit(1)

height = win._origin_height() + win.params.get("mod_balance_height") / 1000.0
print("Trying eight mappings at %.0f mm, %.0f s each."
      % (win.params.get("mod_balance_height"), TRIAL))
print("The ball WILL roll off under the wrong ones -- put it back when asked.\n")

win.serial.send_pose(height, 0.0, 0.0, win.params.get("mod_rise_time"))
wait(win.params.get("mod_rise_time") + 1.2)

print("%-24s %-10s %-12s %s" % ("mapping", "held", "mean dist", "verdict"))
results = []
for swap, inv_x, inv_y in itertools.product((False, True), (False, True), (False, True)):
    label = "swap=%-5s X=%-5s Y=%-5s" % (swap, inv_x, inv_y)
    if not wait_for_ball():
        print("%-24s  -- no ball; put it on the plate --" % label)
        continue
    r = trial(height, swap, inv_x, inv_y)
    if r is None:
        print("%-24s %-10s %-12s lost immediately" % (label, "0.0 s", "-"))
        results.append((0.0, 9999.0, swap, inv_x, inv_y))
        continue
    held, mean, n = r
    verdict = "HOLDS" if held > TRIAL * 0.8 else ("partial" if held > 1.0 else "loses it")
    print("%-24s %-10s %-12s %s"
          % (label, "%.1f s" % held, "%.0f px" % mean, verdict))
    results.append((held, mean, swap, inv_x, inv_y))

win.control.set_enabled(False)
win._armed = False
win.modes.stop()
win.machine_panel.go_origin()
wait(1.5)

print()
if not results:
    print("No trial ran -- the ball was never on the plate.")
else:
    # longest held wins; mean distance breaks ties
    best = max(results, key=lambda r: (round(r[0], 1), -r[1]))
    held, mean, swap, inv_x, inv_y = best
    if held < 1.0:
        print("No mapping held the ball at all. That points past the signs:")
        print("either the two tilt axes are still not independent, or the plate")
        print("is too far off level for any of them to recover.")
    else:
        print("Best: swap=%s  invert X=%s  invert Y=%s   held %.1f s, mean %.0f px"
              % (swap, inv_x, inv_y, held, mean))
        if APPLY:
            win.params.set("ctl_swap_axes", swap)
            win.params.set("ctl_invert_x", inv_x)
            win.params.set("ctl_invert_y", inv_y)
            print("Applied. Put these in params.py to keep them:")
            print("    ctl_swap_axes  %s" % swap)
            print("    ctl_invert_x   %s" % inv_x)
            print("    ctl_invert_y   %s" % inv_y)

win.close()
wait(1.0)
