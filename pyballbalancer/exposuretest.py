"""Find the exposure and gain that measure the ball at its true size.

Detection RATE is not the metric. This rig has twice reported a confident,
stable ball at badly wrong size -- once locked onto the halo the ball throws
onto the ceiling, once seeing only the bright core of an under-exposed ball --
and in both cases every frame "detected". What the settings have to get right
is the RADIUS, because the radius is the ball's distance, and the control loop
now scales its gains by it as well as reading position from the centre.

There is a known answer to check against. The ball is 40 mm across at a
distance the commanded plate height fixes, so optics.py predicts what it
should measure. Anything far off that is the camera lying, not the ball
moving.

    python exposuretest.py

Nothing else may hold the camera. Ball on the plate, plate at the working
origin, hands out of frame.
"""
from __future__ import annotations

import sys

import cv2
import numpy as np

import optics
from camera import _BACKEND, _CONTROLS
from params import ParameterStore
from vision import VisionProcessor

EXPOSURES = (-9, -8, -7, -6, -5)
GAINS = (60, 120, 200)
FRAMES = 60

base = ParameterStore().snapshot()
expected = optics.ball_radius_px(base["mac_origin_offset"])


def trial(exposure, gain, frames=FRAMES):
    cap = cv2.VideoCapture(int(base["cam_index"]), _BACKEND)
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(base["cam_width"]))
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(base["cam_height"]))
    cap.set(cv2.CAP_PROP_FPS, int(base["cam_fps"]))
    p = dict(base, cam_exposure=exposure, cam_gain=gain)
    for key, prop in _CONTROLS:
        value = p[key]
        if key == "cam_auto_exposure":
            value = 1.0 if value else 0.0
        cap.set(prop, float(value))
    for _ in range(12):                    # let the sensor settle after the set
        cap.read()

    vp = VisionProcessor()
    hits, rs, xs, ys, clip = 0, [], [], [], []
    for _ in range(frames):
        ok, frame = cap.read()
        if not ok:
            continue
        det, _mask = vp.process(frame, p)
        v = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)[:, :, 2]
        clip.append(100.0 * float((v >= 254).mean()))
        if det is not None:
            hits += 1
            rs.append(det.radius)
            xs.append(det.x)
            ys.append(det.y)
    cap.release()
    if not rs:
        return dict(hits=hits, frames=frames, radius=0.0, sd=0.0,
                    jitter=0.0, clip=float(np.mean(clip)) if clip else 0.0)
    return dict(hits=hits, frames=frames, radius=float(np.mean(rs)),
                sd=float(np.std(rs)),
                jitter=float(np.hypot(np.std(xs), np.std(ys))),
                clip=float(np.mean(clip)))


print("Ball on the plate at the working origin (%.0f mm), so it should measure "
      "%.1f px.\n" % (base["mac_origin_offset"], expected))
print(" exp gain   found    radius        err   clip%%  centre jitter")
best = None
for exposure in EXPOSURES:
    for gain in GAINS:
        r = trial(exposure, gain)
        if r is None:
            print("  camera busy - close the GUI first")
            sys.exit(1)
        err = (100.0 * (r["radius"] / expected - 1.0)) if r["radius"] else float("nan")
        print("  %3d %4d  %3d/%d  %6.1f +-%4.1f  %+6.1f%%  %5.1f      %.1f px"
              % (exposure, gain, r["hits"], r["frames"], r["radius"], r["sd"],
                 err, r["clip"], r["jitter"]))
        # Rank on honesty first, then on how often it sees anything: a setting
        # that finds the ball every frame at the wrong size is worse than one
        # that finds it slightly less often at the right size.
        if r["radius"] > 0:
            score = (abs(err) > 15.0, -r["hits"], abs(err), r["clip"])
            if best is None or score < best[0]:
                best = (score, exposure, gain, r, err)

print()
if best is None:
    print("Nothing detected at any setting. Check the ball is in frame and lit,")
    print("and that the colour gate matches it, before tuning exposure further.")
    sys.exit(1)
_score, exposure, gain, r, err = best
print("Best: exposure %d, gain %d - %d/%d frames, %.1f px against %.1f expected "
      "(%+.1f%%), %.1f%% clipped." % (exposure, gain, r["hits"], r["frames"],
                                      r["radius"], expected, err, r["clip"]))
if abs(err) > 15.0:
    print()
    print("That is still well off. A ball reading SMALL is under-exposed - only")
    print("its core passes the colour gate. A ball reading LARGE is usually the")
    print("halo it throws onto the ceiling, not the ball. Neither shows up as a")
    print("drop in detection rate, which is why this tool measures size.")
elif (exposure, gain) != (base["cam_exposure"], base["cam_gain"]):
    print("Set cam_exposure %d and cam_gain %d on the Camera tab (currently "
          "%g / %g)." % (exposure, gain, base["cam_exposure"], base["cam_gain"]))
else:
    print("That is what the app already ships. Nothing to change.")
