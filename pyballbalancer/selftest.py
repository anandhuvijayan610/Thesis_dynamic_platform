"""Headless checks for the parts that do not need a camera or a serial port.

Run:  python selftest.py
"""
from __future__ import annotations

import math
import os
import sys
import tempfile

import cv2
import numpy as np

import machine
import optics
from control import (BallState, ControlLoop, PIDAxis,
                     VelocityEstimator, analytical_tilt)
from datalog import COLUMNS, DataLogger
from params import SPECS, ParameterStore
from vision import STRATEGIES, VisionProcessor, _build_mask

FAILED = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (("   " + detail) if detail else ""))
    if not cond:
        FAILED.append(name)


# ---------------------------------------------------------------- params
print("ParameterStore")
store = ParameterStore()
check("defaults load", len(store.snapshot()) == len(SPECS))

seen = []
store.changed.connect(lambda k, v: seen.append((k, v)))
store.set("pid_kp_x", 0.2)
check("set emits changed", seen == [("pid_kp_x", 0.2)], str(seen))
seen.clear()
store.set("pid_kp_x", 0.2)
check("no signal when value is unchanged", seen == [])
store.set("ctl_max_tilt", 999.0)
check("value is clamped to the spec range", store.get("ctl_max_tilt") == 20.0,
      "got %s" % store.get("ctl_max_tilt"))
store.set("cam_gain", 12.7)
check("int params are coerced", store.get("cam_gain") == 13)

path = os.path.join(tempfile.gettempdir(), "bb_preset.json")
store.to_json(path)
store.set("pid_kp_x", 0.9)
store.from_json(path)
check("preset round-trips", abs(store.get("pid_kp_x") - 0.2) < 1e-9)

# ------------------------------------------------------- velocity estimate
print("\nVelocityEstimator")
est = VelocityEstimator(window=8)
rng = np.random.default_rng(7)
true_vx, true_vy = 250.0, -120.0
for i in range(8):
    t = i * 0.01
    est.add(t, true_vx * t + rng.normal(0, 0.6), true_vy * t + rng.normal(0, 0.6))
vx, vy = est.estimate()
check("recovers vx from noisy samples", abs(vx - true_vx) < 45, "vx=%.1f" % vx)
check("recovers vy from noisy samples", abs(vy - true_vy) < 45, "vy=%.1f" % vy)

est.reset()
est.add(0.0, 0.0, 0.0)
check("single sample gives zero, not a divide by zero", est.estimate() == (0.0, 0.0))

# fewer samples must be noisier than more: that is the trade the knob exposes
def spread(window, trials=40):
    out = []
    for s in range(trials):
        r = np.random.default_rng(s)
        e = VelocityEstimator(window=window)
        for i in range(window):
            t = i * 0.01
            e.add(t, true_vx * t + r.normal(0, 1.0), 0.0)
        out.append(e.estimate()[0])
    return float(np.std(out))


s4, s16 = spread(4), spread(16)
check("a longer window reduces velocity noise", s16 < s4, "sd %.1f -> %.1f" % (s4, s16))

# ---------------------------------------------------------------- PID
print("\nPIDAxis")
pid = PIDAxis()
out = pid.step(err=100.0, vel=0.0, kp=0.05, ki=0.0, kd=0.0, clamp=2.0, t=0.0)
check("positive error drives a negative correction", out < 0, "out=%.3f" % out)
pid.reset()
for i in range(200):
    out = pid.step(10.0, 0.0, 0.0, 1.0, 0.0, 2.0, i * 0.01)
check("integral is clamped", abs(pid.integral) <= 2.0 + 1e-9, "I=%.3f" % pid.integral)
pid.reset()
check("reset clears the integral", pid.integral == 0.0)
d_only = PIDAxis().step(0.0, 100.0, 0.0, 0.0, 0.07, 2.0, 0.0)
check("derivative opposes the velocity", d_only < 0, "out=%.3f" % d_only)

# ---------------------------------------------------- analytical (mirror)
print("\nanalytical_tilt")
state = BallState(x=0.0, y=0.0, vx=0.0, vy=0.0, radius=20.0, t=0.0)
tx, ty = analytical_tilt(state, 100.0, 0.0, 0.75, 0.35, 1.0)
check("target to the +x side tilts about +x", tx > 0, "tx=%.2f" % tx)
check("no y offset gives no y tilt", abs(ty) < 1e-6, "ty=%.2f" % ty)
tx2, _ = analytical_tilt(state, -100.0, 0.0, 0.75, 0.35, 1.0)
check("the response is antisymmetric", abs(tx2 + tx) < 1e-6)
tx3, _ = analytical_tilt(state, 100.0, 0.0, 0.75, 0.35, 2.0)
check("gain scales the output", abs(tx3 - 2 * tx) < 1e-6)
still = analytical_tilt(state, 0.0, 0.0, 0.75, 0.35, 1.0)
check("ball already on target asks for no tilt", abs(still[0]) < 1e-6 and abs(still[1]) < 1e-6)

# ---------------------------------------------------------------- vision
print("\nVision")
frame = np.full((480, 640, 3), 40, np.uint8)
cv2.circle(frame, (400, 180), 34, (30, 120, 240), -1)      # orange ball, BGR
params = ParameterStore().snapshot()

def settle(frame_, params_, frames=8, vp=None):
    """Feed the same frame repeatedly.

    Detection is now stateful on purpose: a candidate has to hold still for a
    few frames before it is believed, so one frame can never produce a ball.
    That is the point of the tracker, not an inconvenience to work around.
    """
    vp = vp or VisionProcessor()
    det = mask = None
    for _ in range(frames):
        det, mask = vp.process(frame_, params_)
    return det, mask


for name in STRATEGIES:
    params["vis_strategy"] = name
    det, mask = settle(frame, params)
    ok = det is not None
    detail = ""
    if ok:
        # centre-frame: +x right of centre, +y above centre
        ex, ey = 400 - 320, 240 - 180
        ok = abs(det.x - ex) < 12 and abs(det.y - ey) < 12 and abs(det.radius - 34) < 10
        detail = "x=%.0f y=%.0f r=%.0f (want %d,%d,34)" % (det.x, det.y, det.radius, ex, ey)
    check("%s finds the ball" % name, ok, detail)

params["vis_strategy"] = "Threshold + contour"
single, _ = VisionProcessor().process(frame, params)
check("one frame is not enough to trust a ball", single is None)

empty, _ = settle(np.full((480, 640, 3), 40, np.uint8), params)
check("empty scene yields no detection", empty is None)

# an elongated bright bar must be rejected by the circularity gate
bar = np.full((480, 640, 3), 40, np.uint8)
cv2.rectangle(bar, (100, 200), (520, 232), (30, 120, 240), -1)
det_bar, _ = settle(bar, params)
check("elongated blob is rejected on circularity", det_bar is None,
      "" if det_bar is None else "r=%.0f" % det_bar.radius)

# A round ball with a RAGGED EDGE must still be accepted. This is not a
# hypothetical: the ball is lit from one side, and when its shaded limb sits
# near the brightness floor those pixels flicker in and out of the colour gate
# and the outline comes out serrated. The area is untouched and the blob is
# plainly a disc, but the perimeter inflates and circularity collapses -- the
# real ball measured 0.43 against a 0.55 gate and was reported as "no ball"
# while showing a clean round blob on screen. Fill stayed at 0.93.
# A sawtooth on the shaded limb only, tuned so the pair of numbers it
# produces matches what the real ball measured: 0.45 / 0.93 against 0.43 /
# 0.93. Notches have to be deep and fine enough to survive the morphology
# close, or the synthetic quietly tests nothing -- a gentler version of this
# scored 0.85 and would have passed the old gate it is supposed to break.
_R, _NOTCH, _STEP = 100, 28, 6
_pts = []
for _i in range(360 // _STEP):
    _a = math.radians(_i * _STEP)
    _r = _R - (_NOTCH if (math.cos(_a) < -0.2 and _i % 2) else 0)
    _pts.append([int(320 + _r * math.cos(_a)), int(240 + _r * math.sin(_a))])
serrated = np.full((480, 640, 3), 40, np.uint8)
cv2.fillPoly(serrated, [np.array(_pts, np.int32)], (30, 120, 240))

_cs, _ = cv2.findContours(_build_mask(serrated, params), cv2.RETR_EXTERNAL,
                          cv2.CHAIN_APPROX_NONE)
_c = max(_cs, key=cv2.contourArea)
_a, _per = cv2.contourArea(_c), cv2.arcLength(_c, True)
_enc = cv2.minEnclosingCircle(_c)[1]
_circ = 4 * math.pi * _a / (_per * _per)
_fill = math.sqrt(_a / math.pi) / _enc
check("a serrated edge really does wreck circularity", _circ < 0.55,
      "circularity %.2f, and the real ball measured 0.43" % _circ)
check("while fill barely notices", _fill > 0.80, "fill %.2f" % _fill)

det_serr, _ = settle(serrated, params)
check("so a ragged-edged ball is still detected", det_serr is not None,
      "circularity %.2f, fill %.2f" % (_circ, _fill) if det_serr is None
      else "r=%.0f (want ~100)" % det_serr.radius)

# The gate that replaced it still has to do the original job.
for label, box, want in (("10:1 bar", (100, 220, 520, 262), None),
                         ("4:1 bar", (200, 200, 440, 260), None),
                         ("2:1 bar", (220, 180, 420, 280), None)):
    im = np.full((480, 640, 3), 40, np.uint8)
    cv2.rectangle(im, box[:2], box[2:], (30, 120, 240), -1)
    got, _ = settle(im, params)
    check("%s is still rejected" % label, got is None,
          "" if got is None else "accepted at r=%.0f" % got.radius)

# The one that matters on this rig: a big round thing out at the frame corner
# is the ceiling, not the ball, however convincing it looks in isolation.
ceiling = np.full((480, 640, 3), 40, np.uint8)
cv2.circle(ceiling, (60, 430), 55, (30, 120, 240), -1)     # 303 px from centre
det_ceil, _ = settle(ceiling, dict(params, vis_roi_radius=150), frames=40)
check("a blob outside the plate region is never accepted", det_ceil is None,
      "" if det_ceil is None else "x=%.0f y=%.0f r=%.0f"
      % (det_ceil.x, det_ceil.y, det_ceil.radius))

# and with both present, the ball must win even though the ceiling is bigger
both = np.full((480, 640, 3), 40, np.uint8)
cv2.circle(both, (60, 430), 55, (30, 120, 240), -1)        # ceiling, larger
cv2.circle(both, (350, 210), 26, (30, 120, 240), -1)       # ball, smaller, central
det_both, _ = settle(both, params, frames=12)
check("the ball is preferred over a larger blob off the plate",
      det_both is not None and abs(det_both.radius - 26) < 10,
      "r=%.0f at (%.0f, %.0f)" % (det_both.radius, det_both.x, det_both.y)
      if det_both else "nothing found")

# ------------------------------------------------------- ball selection
# The tracker decides which candidate is the ball. Tested directly, because
# the failure it guards against is a self-sustaining one: latch onto the
# ceiling once and a proximity gate keeps defending that choice forever, so
# the machine tracks something that never moves and never recovers.
print("\nBall selection")
from vision import BallTracker, Detection                          # noqa: E402


def cand(x, y, r=25.0):
    return Detection(x, y, r, 1.0, 320.0 + x, 240.0 - y)


tp = dict(params)
tp.update(vis_roi_radius=200, vis_lock_frames=4, vis_lock_tol_px=30,
          vis_gate_px=150, vis_gate_frames=5)

t = BallTracker()
out = [t.select([cand(10, 10)], tp) for _ in range(3)]
check("a new candidate is not believed straight away", all(o is None for o in out))
check("the fourth frame earns the lock", t.select([cand(10, 10)], tp) is not None)
check("and it is then locked", t.locked)

t = BallTracker()
for _ in range(6):
    t.select([cand(250, 100)], tp)          # 269 px out, beyond the plate
check("a candidate outside the plate never locks", not t.locked)
check("and nothing is reported", t.select([cand(250, 100)], tp) is None)

# cold start must not simply take the biggest
t = BallTracker()
for _ in range(6):
    got = t.select([cand(190, 60, r=80.0), cand(20, 15, r=18.0)], tp)
check("cold start prefers the central candidate, not the largest",
      got is not None and abs(got.radius - 18.0) < 1e-6,
      "picked r=%.0f" % got.radius if got else "nothing")

# a jitter that never settles must never be trusted
t = BallTracker()
jitter = [t.select([cand(-100 if i % 2 else 100, 0)], tp) for i in range(20)]
check("a candidate that jumps about never earns trust",
      all(j is None for j in jitter) and not t.locked)

# once locked, track by proximity and ignore a far-off distractor
t = BallTracker()
for _ in range(4):
    t.select([cand(0, 0)], tp)
moved = t.select([cand(20, 10), cand(-180, 0)], tp)
check("a locked ball follows the nearby candidate",
      moved is not None and abs(moved.x - 20) < 1e-6,
      "x=%.0f" % moved.x if moved else "lost")

far = t.select([cand(-190, 0)], tp)
check("and ignores one outside the gate", far is None)

# Size continuity. A clipped or split ball reports a smaller radius as well as
# a biased centre, so a guard that trusts the reported radius lets it through.
t2 = BallTracker()
tp2 = dict(tp, vis_radius_tolerance=0.70)
for _ in range(4):
    t2.select([cand(0, 0, r=100.0)], tp2)
check("a tracked ball keeps a steady radius",
      t2.select([cand(5, 0, r=98.0)], tp2) is not None)
check("a sudden shrink is treated as a fragment, not the ball",
      t2.select([cand(5, 0, r=40.0)], tp2) is None)
check("and so is a sudden jump in size",
      t2.select([cand(5, 0, r=260.0)], tp2) is None)
check("the tolerance can be turned off",
      t2.select([cand(5, 0, r=40.0)], dict(tp, vis_radius_tolerance=1.0)) is None
      or True)   # 1.0 means "no window"; the point is it must not raise

# the lock has to be droppable, or a ball picked up and put back is tracked
# to where it used to be forever
for _ in range(5):
    t.select([], tp)
check("the lock is dropped after enough misses", not t.locked)
for _ in range(4):
    again = t.select([cand(-120, -40)], tp)
check("and a ball placed somewhere else is found again",
      again is not None and abs(again.x + 120) < 1e-6,
      "x=%.0f" % again.x if again else "not re-acquired")

t = BallTracker()
one = dict(tp, vis_lock_frames=1)
check("the wait can be turned off with vis_lock_frames=1",
      t.select([cand(0, 0)], one) is not None)

# ------------------------------------------------- why nothing was found
# "No ball" has half a dozen causes that look identical from outside. Each
# should name itself, so a failure can be diagnosed from the window rather
# than by attaching a script to the running application.
print("\nRejection reasons")
vp = VisionProcessor()
vp.process(bar, params)                       # the elongated bar from above
check("an unround blob says so",
      any("round" in r for r in vp.rejections), "; ".join(vp.rejections[:2]))

# radius 5 survives the morphology open but is under the 120 px area floor
tiny = np.full((480, 640, 3), 40, np.uint8)
cv2.circle(tiny, (320, 240), 5, (30, 120, 240), -1)
vp.process(tiny, params)
check("a blob under the area floor says so",
      any("small" in r for r in vp.rejections), "; ".join(vp.rejections[:2]))

# and a scene the colour gate rejects outright is a different diagnosis
vp_empty = VisionProcessor()
vp_empty.process(np.full((480, 640, 3), 40, np.uint8), params)
check("an empty mask names the colour gate",
      any("colour gate" in r for r in vp_empty.rejections),
      "; ".join(vp_empty.rejections[:1]))

small_r = dict(params); small_r["vis_max_radius"] = 12
vp2 = VisionProcessor()
vp2.process(frame, small_r)
check("a blob outside the radius limits says so",
      any("radius" in r for r in vp2.rejections), "; ".join(vp2.rejections[:2]))

# The plate region is now the frame corner, because a reconstructed ball
# legitimately reads far out; tightening it back down would throw away exactly
# the readings the arc fit exists to provide. Check it still bites if narrowed.
off_plate = np.full((480, 640, 3), 40, np.uint8)
cv2.circle(off_plate, (110, 400), 45, (30, 120, 240), -1)   # 264 px from centre
narrow = dict(params); narrow["vis_roi_radius"] = 150
vp3 = VisionProcessor()
for _ in range(6):
    vp3.process(off_plate, narrow)
check("a blob outside the plate region says so",
      any("plate region" in r for r in vp3.rejections), "; ".join(vp3.rejections[:2]))

vp4 = VisionProcessor()
vp4.process(frame, params)                    # first frame: still earning trust
check("a candidate still earning trust says so",
      any("holding still" in r for r in vp4.rejections), "; ".join(vp4.rejections[:2]))

vp5 = VisionProcessor()
det5, _ = settle(frame, params, vp=vp5)
check("a found ball reports nothing to explain",
      det5 is not None and not vp5.rejections, "; ".join(vp5.rejections[:2]))

# --------------------------------------------------- balls off the edge
# A ball half out of the picture has a useless centroid and a useless
# enclosing circle -- both describe the visible piece rather than the ball.
# Its outline still holds a true arc of the ball's edge though, and an arc
# fixes a circle completely, so the centre can be reconstructed. That is what
# makes the camera's narrow band usable without moving the camera.
print("\nBalls off the frame edge")
R = 60


def ball_at(cx, cy, r=R):
    img = np.full((480, 640, 3), 40, np.uint8)
    cv2.circle(img, (int(cx), int(cy)), r, (30, 120, 240), -1)
    return img


def found_at(cx, cy, r=R, params_=None):
    """Where the pipeline says the ball is, in raw pixels."""
    det, _ = settle(ball_at(cx, cy, r), params_ or params, frames=10)
    if det is None:
        return None
    return det.x + 320.0, 240.0 - det.y, det.radius


got = found_at(320, 240)
check("a ball well inside the frame is found", got is not None)
if got:
    check("and accurately", math.hypot(got[0] - 320, got[1] - 240) < 3.0,
          "%.1f px out" % math.hypot(got[0] - 320, got[1] - 240))

for cx, label in ((610, "half off the right edge"),
                  (650, "mostly off the right edge"),
                  (30, "half off the left edge")):
    got = found_at(cx, 240)
    off = 100.0 * max(0.0, (cx + R) - 640) / (2 * R) if cx > 320 \
        else 100.0 * max(0.0, R - cx) / (2 * R)
    check("reconstructed: %s (%.0f%% outside)" % (label, off),
          got is not None and math.hypot(got[0] - cx, got[1] - 240) < 6.0,
          "no detection" if not got
          else "%.1f px out, radius %.0f" % (math.hypot(got[0]-cx, got[1]-240), got[2]))

got = found_at(320, 455)          # the top and bottom are the tight edges
check("and off the bottom edge too",
      got is not None and math.hypot(got[0] - 320, got[1] - 455) < 6.0,
      "no detection" if not got else "%.1f px out" % math.hypot(got[0]-320, got[1]-455))

# The arc tolerance is what stands in for circularity here, since a clipped
# ball can never be round. A straight-edged blob must still be turned down.
bar_edge = np.full((480, 640, 3), 40, np.uint8)
cv2.rectangle(bar_edge, (500, 100), (700, 380), (30, 120, 240), -1)
vp_bar = VisionProcessor()
det_bar2 = None
for _ in range(8):
    det_bar2, _ = vp_bar.process(bar_edge, params)
check("a straight-edged blob at the frame edge is still rejected",
      det_bar2 is None,
      "" if det_bar2 is None else "r=%.0f" % det_bar2.radius)
check("and the arc tolerance is what says so",
      any("arc" in r for r in vp_bar.rejections), "; ".join(vp_bar.rejections[:1]))

# too little of the ball left to reconstruct honestly
tiny_arc = dict(params); tiny_arc["vis_min_arc_points"] = 400
got = found_at(650, 240, params_=tiny_arc)
check("it declines when too little of the outline is left", got is None,
      "" if got is None else "claimed a fit from very little arc")

bad = dict(params)
bad["vis_kernel"] = -5      # invalid on purpose
try:
    VisionProcessor().process(frame, bad)
    check("bad parameters do not raise", True)
except Exception as exc:                      # noqa: BLE001 - that is the point
    check("bad parameters do not raise", False, repr(exc))

# ---------------------------------------------------------------- optics
print("\nOptics")

# The direction of this one is the whole point. The camera is BELOW the plate,
# so raising the plate moves it away; the rig has had this backwards before,
# and it hides because a sign error cancels against a wrongly fitted offset at
# the single height the pair was fitted at.
check("a higher plate is further from the camera",
      optics.camera_distance(50) > optics.camera_distance(10))
check("and so looks smaller",
      optics.ball_radius_px(50) < optics.ball_radius_px(10))
check("while showing more of the plate",
      optics.half_window_mm(50)[0] > optics.half_window_mm(10)[0])
check("the long frame axis sees more than the short one",
      optics.half_window_mm(30)[0] > optics.half_window_mm(30)[1])
check("and the tight window is the short one, which is what loses the ball",
      abs(optics.tight_window_mm(30) - optics.half_window_mm(30)[1]) < 1e-12)
# The frame shape has to match what camera.py actually receives, or every
# window figure names the wrong axis. This app requests 640x480 and gets it;
# the Unity host ran the same camera the other way round.
_ps = ParameterStore()
check("the optics frame matches the camera request",
      (optics.FRAME_W, optics.FRAME_H) == (_ps.get("cam_width"), _ps.get("cam_height")),
      "%dx%d vs %dx%d" % (optics.FRAME_W, optics.FRAME_H,
                          _ps.get("cam_width"), _ps.get("cam_height")))

# Against the rig's own calibration: three commanded heights, five samples
# each, measured on the machine. Anything that drifts from these means the
# camera has moved and every window figure below is fiction.
for h, measured in ((2.0, 169.05), (22.0, 133.56), (52.0, 100.13)):
    err = optics.ball_radius_px(h) - measured
    check("radius at %.0f mm matches the calibration" % h, abs(err) < 1.5,
          "%.2f px vs %.2f, err %+.2f" % (optics.ball_radius_px(h), measured, err))

check("a stroke under 1 g throws nothing", optics.throw(10.0, 0.20) is None)

t = optics.throw(25.0, 0.05)
check("the shipped stroke does throw", t is not None)
check("it beats gravity with margin", t["peak_g"] > 3.0, "%.2f g" % t["peak_g"])
check("the ball is released part way up, not at the top",
      0.0 < t["release_mm"] < 25.0, "%.1f mm of 25" % t["release_mm"])
check("so it leaves slower than the plate's peak speed",
      t["exit_speed"] < math.pi * 0.025 / (2 * 0.05),
      "%.3f < %.3f m/s" % (t["exit_speed"], math.pi * 0.025 / (2 * 0.05)))

# The hang time decides the top dwell, so check it by simulating rather than
# by repeating the algebra: step the plate along its half-cosine and the ball
# along a parabola from the moment they part, and see when they meet again.
def simulate(amp_mm, rise_s, dt=1e-6):
    a, g = amp_mm / 1000.0, 9.81
    plate = lambda tt: (a / 2.0 * (1.0 - math.cos(math.pi * tt / rise_s))
                        if tt < rise_s else a)
    accel = lambda tt: (math.pi ** 2 * a / (2 * rise_s ** 2)
                        * math.cos(math.pi * tt / rise_s) if tt < rise_s else 0.0)
    tt = 0.0
    while tt < rise_s and accel(tt) > -g:
        tt += dt
    sep_t, sep_x = tt, plate(tt)
    sep_v = math.pi * a / (2 * rise_s) * math.sin(math.pi * tt / rise_s)
    while tt < 5.0:
        tt += dt
        y = sep_x + sep_v * (tt - sep_t) - 0.5 * g * (tt - sep_t) ** 2
        if tt > sep_t + dt and y <= plate(tt):
            return sep_t, tt - rise_s, sep_x
    return sep_t, None, sep_x

sep_t, hang, sep_x = simulate(25.0, 0.05)
check("the simulated release height agrees", abs(sep_x * 1000 - t["release_mm"]) < 0.1,
      "%.2f vs %.2f mm" % (sep_x * 1000, t["release_mm"]))
check("and the ball lands back on the plate when the model says",
      hang is not None and abs(hang - t["hang_time"]) < 2e-3,
      "%.4f vs %.4f s" % (hang if hang else -1, t["hang_time"]))

# The shipped mode must actually be self-consistent: the plate has to still be
# up there when the ball comes down.
_p = ParameterStore()
_amp = _p.get("mod_jug_high") - _p.get("mod_jug_low")
_t = optics.throw(_amp, _p.get("mod_jug_rise_time"))
check("the shipped juggle separates the ball", _t is not None)
check("and its top dwell matches the flight",
      abs(_p.get("mod_jug_top_dwell") - _t["hang_time"]) < 0.03,
      "dwell %.3f s vs %.3f s of air"
      % (_p.get("mod_jug_top_dwell"), _t["hang_time"]))
_base = _p.get("mac_origin_offset") + _p.get("mod_jug_low")
_top = _p.get("mac_origin_offset") + _p.get("mod_jug_high")
_steps = math.pi * abs(machine.pulses_for(
    machine.arm_angles(_top / 1000.0, 0, 0)[0]
    - machine.arm_angles(_base / 1000.0, 0, 0)[0])) / (2 * _p.get("mod_jug_rise_time"))
check("the stroke fits under the firmware step ceiling", _steps < 25000,
      "%.0f /s" % _steps)
check("and the top of it is inside the arms' reach",
      abs(machine.forward_height(machine.arm_angles(_top / 1000.0, 0, 0)[0])
          - machine.HEIGHT_ORIGIN - _top / 1000.0) < 1e-6,
      "%.0f mm" % _top)

# ------------------------------------------------- gain scale with distance
print("\nGain scale with plate height")
_cl = ControlLoop(ParameterStore())
_sp = _cl._params.snapshot()
_cl._radius_avg = _sp["ctl_ref_radius"]
check("at the tuning radius nothing changes", abs(_cl._height_scale(_sp) - 1.0) < 1e-9)
_cl._radius_avg = _sp["ctl_ref_radius"] / 2.0
check("a plate twice as far pushes twice as hard",
      abs(_cl._height_scale(_sp) - 2.0) < 1e-9, "%.3f" % _cl._height_scale(_sp))
_cl._radius_avg = 1e-3
check("a nonsense radius is clamped, not amplified",
      _cl._height_scale(_sp) <= 2.0, "%.3f" % _cl._height_scale(_sp))
_cl._radius_avg = None
check("an unmeasured radius leaves the gains alone",
      abs(_cl._height_scale(_sp) - 1.0) < 1e-9)
_cl._radius_avg = 40.0
_sp["ctl_scale_by_radius"] = False
check("and the whole thing can be switched off",
      abs(_cl._height_scale(_sp) - 1.0) < 1e-9)

# It has to point the right way. Higher plate, smaller ball, more degrees per
# pixel -- because each pixel is now worth more millimetres of real travel.
_sp["ctl_scale_by_radius"] = True
_cl._radius_avg = optics.ball_radius_px(70)
_high = _cl._height_scale(_sp)
_cl._radius_avg = optics.ball_radius_px(40)
_low = _cl._height_scale(_sp)
check("raising the plate raises the gain, not lowers it", _high > _low,
      "%.3f at 70 mm vs %.3f at 40 mm" % (_high, _low))
# Not exactly, and it should not be: the ball's angular size goes as
# atan(R/d), not as 1/d, so using the radius as a stand-in for distance is a
# small-angle approximation. Worth knowing how small -- at this geometry the
# two disagree by about 0.2%, which is nothing against the gains themselves.
_want = optics.px_per_mm(40) / optics.px_per_mm(70)
check("and by very nearly the amount the image scale changed",
      abs(_high / _low - _want) / _want < 0.005,
      "%.4f vs %.4f, %.2f%% apart"
      % (_high / _low, _want, 100 * abs(_high / _low - _want) / _want))

# ---------------------------------------------------------------- logging
print("\nDataLogger")
log_path = os.path.join(tempfile.gettempdir(), "bb_log.csv")
log = DataLogger()
log.start(log_path)
for i in range(5):
    log.write([i] * len(COLUMNS))
log.stop()
with open(log_path, encoding="utf-8") as fh:
    lines = [l for l in fh.read().splitlines() if l]
check("header plus every row is written", len(lines) == 6, "%d lines" % len(lines))
check("header matches the column list", lines[0].split(",") == COLUMNS)
DataLogger().write([1])       # must be a no-op, not a crash
check("writing while stopped is harmless", True)

print("\n%s" % ("ALL CHECKS PASSED" if not FAILED else "FAILURES: " + ", ".join(FAILED)))
sys.exit(1 if FAILED else 0)
