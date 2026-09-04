"""Trim the plate level while the controller holds the ball.

autolevel.py measures the slope open-loop, with the plate commanded flat. That
only works if the plate is already nearly level: on a real slope the ball rolls
out of view before a reading finishes, which is exactly when the measurement is
wanted most.

Under closed loop the problem inverts. A correctly signed controller keeps the
ball on the plate, and a proportional loop against a constant disturbance
settles at a standing offset proportional to it. So the ball's average position
while balancing *is* a slope measurement, taken with the ball safely held. Trim
until that offset is gone and the plate is level in the only sense that
matters: the ball sits in the middle with the controller doing nothing.

    python centretrim.py            measure and report
    python centretrim.py --apply    and keep the trim it finds

Requires the axis mapping to be right -- run mappingsearch.py first if the
controller cannot hold the ball at all.
"""
from __future__ import annotations

import math
import sys
import time

from PyQt5.QtWidgets import QApplication

from gui import MainWindow

APPLY = "--apply" in sys.argv

# The loop was measured holding the ball about 4.4 s before losing it, so
# the whole trial has to fit inside that with room to spare. An average taken
# over a window the ball does not survive is not an average of anything.
SETTLE = 0.9          # let the loop reach its standing offset before averaging
WINDOW = 1.4          # average the offset over this
ROUNDS = 6
GOOD_PX = 25.0        # stop once the ball sits this close to the middle
MAX_STEP = 0.25       # degrees of trim per round

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


def wait_for_ball(seconds=25.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        wait(0.05)
        if ball() is not None:
            return True
    return False


def offset(height):
    """Mean ball position while the loop holds it. None if it was lost."""
    win.camera.reset_tracking()
    wait(0.3)
    win.modes.start("Balancing")
    win._armed = True
    win.control.set_enabled(True)

    wait(SETTLE)
    xs, ys = [], []
    end = time.monotonic() + WINDOW
    while time.monotonic() < end:
        wait(0.02)
        b = ball()
        if b is not None:
            xs.append(b[0])
            ys.append(b[1])

    win.control.set_enabled(False)
    win._armed = False
    win.modes.stop()
    win.serial.send_pose(height, 0.0, 0.0, 0.5)
    wait(0.6)
    if len(xs) < 15:
        return None
    return sum(xs) / len(xs), sum(ys) / len(ys), len(xs)


wait(4.0)
if not win.serial.is_open:
    print("no serial link — close the GUI if it is still open")
    sys.exit(1)

height = win._origin_height() + win.params.get("mod_balance_height") / 1000.0
kp = win.params.get("pid_kp_x")
start = (win.params.get("mac_trim_x"), win.params.get("mac_trim_y"))
print("Trimming at %.0f mm, under closed loop." % win.params.get("mod_balance_height"))
print("mapping: swap=%s X=%s Y=%s   trim X %+.2f Y %+.2f"
      % (win.params.get("ctl_swap_axes"), win.params.get("ctl_invert_x"),
         win.params.get("ctl_invert_y"), start[0], start[1]))

win.serial.send_pose(height, 0.0, 0.0, win.params.get("mod_rise_time"))
wait(win.params.get("mod_rise_time") + 1.2)

print("\n%-6s %-22s %-20s %s" % ("round", "trim X / Y (deg)", "ball sits at (px)", "note"))
best = None
for rnd in range(1, ROUNDS + 1):
    if not wait_for_ball():
        print("%-6d  -- no ball; put it back on the plate --" % rnd)
        break
    got = offset(height)
    if got is None:
        print("%-6d  -- lost the ball during the trial --" % rnd)
        continue
    mx, my, n = got
    dist = math.hypot(mx, my)
    print("%-6d %-22s %-20s %d samples"
          % (rnd, "%+.2f / %+.2f" % (win.params.get("mac_trim_x"),
                                     win.params.get("mac_trim_y")),
             "%+6.0f, %+6.0f  (%.0f)" % (mx, my, dist), n))
    if best is None or dist < best[0]:
        best = (dist, win.params.get("mac_trim_x"), win.params.get("mac_trim_y"))
    if dist < GOOD_PX:
        print("%-6s centred" % "")
        break

    # A proportional loop parks at an offset proportional to the disturbance,
    # so the offset points straight at the trim correction. The controller
    # drives a positive error negative, so the trim that removes a +x offset
    # is itself negative; the step is capped because the relation is only
    # linear while nothing is saturating.
    step_x = max(-MAX_STEP, min(MAX_STEP, -kp * mx * 0.4))
    step_y = max(-MAX_STEP, min(MAX_STEP, -kp * my * 0.4))
    win.params.set("mac_trim_x", win.params.get("mac_trim_x") + step_x)
    win.params.set("mac_trim_y", win.params.get("mac_trim_y") + step_y)

win.control.set_enabled(False)
win._armed = False
win.modes.stop()
win.machine_panel.go_origin()
wait(1.5)

print("\n----------------------------------------------------------")
print("  trim was  X %+.2f  Y %+.2f" % start)
if best is not None:
    print("  best      X %+.2f  Y %+.2f   ball %.0f px from centre"
          % (best[1], best[2], best[0]))
    if APPLY:
        win.params.set("mac_trim_x", best[1])
        win.params.set("mac_trim_y", best[2])
        print("\n  Kept. Put these in params.py to make them the defaults:")
        print("      mac_trim_x default %.2f" % best[1])
        print("      mac_trim_y default %.2f" % best[2])
    else:
        win.params.set("mac_trim_x", start[0])
        win.params.set("mac_trim_y", start[1])
        print("\n  Not kept — re-run with --apply to keep them.")
else:
    print("  nothing measured")
print("----------------------------------------------------------")

win.close()
wait(1.0)
