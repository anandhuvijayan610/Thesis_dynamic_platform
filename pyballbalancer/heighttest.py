"""Is the ball still visible once the plate is raised?

Raising the plate moves the ball toward the camera, so it grows in the frame.
If it outgrows `vis_max_radius`, or its edge leaves the plate region, detection
stops — and a controller with no ball holds level while the ball rolls away.
That failure looks exactly like a controller with the tilt signs reversed, so
it has to be ruled out before anything is inverted.

Put the ball on the plate near the centre, then:

    python heighttest.py
"""
from __future__ import annotations

import math
import sys
import time

from PyQt5.QtWidgets import QApplication

from gui import MainWindow

app = QApplication(sys.argv)
win = MainWindow()
win.show()


def wait(seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.004)


def sample(seconds: float = 1.2):
    """Detection rate and geometry over a short window."""
    hits, radii, dists = 0, [], []
    total = 0
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        wait(0.02)
        total += 1
        s = win._state
        if s is not None:
            hits += 1
            radii.append(s.radius)
            dists.append(math.hypot(s.x, s.y))
    return hits, total, radii, dists


wait(4.0)
if not win.serial.is_open:
    print("no serial link — is the GUI still open somewhere?")
    sys.exit(1)

p = win.params
print("limits: radius %d..%d px, plate region %d px, lock %d frames"
      % (p.get("vis_min_radius"), p.get("vis_max_radius"),
         p.get("vis_roi_radius"), p.get("vis_lock_frames")))
print("origin %.0f mm, balancing height %.0f mm above it\n"
      % (p.get("mac_origin_offset"), p.get("mod_balance_height")))

print("%-10s %-12s %-18s %-18s %s" % ("height", "detected", "radius px", "from centre px", "verdict"))
for mm in (0, 10, 20, 30, 40, 50):
    win.machine_panel.go_height(mm)
    wait(p.get("mac_move_time") + 1.0)
    win.camera.reset_tracking()
    wait(0.4)
    hits, total, radii, dists = sample()

    if not radii:
        why = win.camera._vision.rejections
        verdict = "LOST: " + (why[0] if why else "no reason recorded")
        rtxt, dtxt = "-", "-"
    else:
        rlo, rhi = min(radii), max(radii)
        dlo, dhi = min(dists), max(dists)
        rtxt = "%.0f..%.0f" % (rlo, rhi)
        dtxt = "%.0f..%.0f" % (dlo, dhi)
        reasons = []
        if rhi >= p.get("vis_max_radius") * 0.95:
            reasons.append("at the radius ceiling")
        if dhi >= p.get("vis_roi_radius") * 0.9:
            reasons.append("near the plate-region edge")
        verdict = ", ".join(reasons) if reasons else "ok"
    print("%-10s %-12s %-18s %-18s %s"
          % ("%+d mm" % mm, "%d/%d" % (hits, total), rtxt, dtxt, verdict))

win.machine_panel.go_origin()
wait(1.2)
win.close()
wait(1.0)
print("\nA 'LOST' row is the answer on its own: the controller sees no ball at")
print("that height, holds level, and the ball simply rolls away.")
