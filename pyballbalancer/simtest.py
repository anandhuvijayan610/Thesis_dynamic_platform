"""Closed-loop simulation.

Compiling and starting threads says nothing about whether the controller
stabilises anything. This runs the real PID and velocity estimator against a
simulated ball on a tilting plate and checks that it converges, that it does
so from several starting states, and that it degrades sensibly when the loop
delay grows.

Plant: a ball rolling on a plate tilted by phi accelerates at c*g*sin(phi),
with c = 5/7 for a solid sphere. Positions are in mm here; the units only have
to be consistent between plant and gains.
"""
from __future__ import annotations

import math
import sys
from collections import deque

from control import PIDAxis, VelocityEstimator

G = 9810.0          # mm/s^2
C_ROLL = 5.0 / 7.0  # solid sphere
FAILED = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (("   " + detail) if detail else ""))
    if not cond:
        FAILED.append(name)


def simulate(x0, v0, kp, kd, target=0.0, delay_s=0.015, dt=0.01, seconds=6.0,
             max_tilt=5.0, noise=0.0, seed=1, slew=0.0):
    """Run the real controller against the plant. Returns the position history."""
    import random
    rng = random.Random(seed)

    pid = PIDAxis()
    est = VelocityEstimator(window=6)
    x, v, t = x0, v0, 0.0
    last = 0.0
    # commands take effect after a transport delay, as they do on the machine
    pipeline = deque([0.0] * max(1, int(round(delay_s / dt))))
    history = []

    while t < seconds:
        measured = x + (rng.gauss(0.0, noise) if noise else 0.0)
        est.add(t, measured, 0.0)
        vx, _ = est.estimate()

        tilt = pid.step(measured - target, vx, kp, 0.0, kd, 2.0, t)
        tilt = max(-max_tilt, min(max_tilt, tilt))
        if slew > 0.0:
            # same limiter the ControlLoop applies, in deg/s
            step = slew * dt
            tilt = last + max(-step, min(step, tilt - last))
        last = tilt
        pipeline.append(tilt)
        applied = pipeline.popleft()

        a = C_ROLL * G * math.sin(math.radians(applied))
        v += a * dt
        x += v * dt
        # the plate is finite: once the ball is off it, the run has failed
        if abs(x) > 400.0:
            history.append(x)
            break
        t += dt
        history.append(x)
    return history


def settled(history, tol=8.0, tail=80):
    return len(history) >= tail and all(abs(v) < tol for v in history[-tail:])


print("Closed-loop simulation — tuned gains (kp=0.05, kd=0.07)")
for x0, v0, label in ((120.0, 0.0, "released 120 mm off centre"),
                      (-80.0, 0.0, "released -80 mm off centre"),
                      (0.0, 400.0, "struck at 400 mm/s from centre"),
                      (60.0, -250.0, "offset and moving back")):
    h = simulate(x0, v0, kp=0.05, kd=0.07)
    check(label, settled(h), "final %+.1f mm, peak %.0f mm" % (h[-1], max(abs(v) for v in h)))

print("\nThe inherited gains should NOT settle (kp=0.05, kd=0.005)")
h = simulate(120.0, 0.0, kp=0.05, kd=0.005)
check("under-damped gains fail to settle", not settled(h),
      "final %+.1f mm, peak %.0f mm" % (h[-1], max(abs(v) for v in h)))

print("\nDerivative term is what stabilises it")
h_nod = simulate(120.0, 0.0, kp=0.05, kd=0.0)
check("proportional only does not settle", not settled(h_nod),
      "peak %.0f mm" % max(abs(v) for v in h_nod))

print("\nRobustness")
h = simulate(120.0, 0.0, kp=0.05, kd=0.07, noise=1.5)
check("settles with 1.5 mm measurement noise", settled(h, tol=15.0),
      "final %+.1f mm" % h[-1])

h = simulate(120.0, 0.0, kp=0.05, kd=0.07, delay_s=0.05)
check("still settles at 50 ms loop delay", settled(h, tol=15.0),
      "final %+.1f mm" % h[-1])


def crossings(history):
    return sum(1 for a, b in zip(history, history[1:]) if a * b < 0)


# Measured tolerance of this gain pair: it settles out to about 150 ms and
# gives up between there and 200 ms. Ringing grows well before that, so the
# crossing count is the earlier warning.
h150 = simulate(120.0, 0.0, kp=0.05, kd=0.07, delay_s=0.15, seconds=12.0)
h200 = simulate(120.0, 0.0, kp=0.05, kd=0.07, delay_s=0.20, seconds=12.0)
check("150 ms delay still settles, but rings", settled(h150, tol=15.0),
      "final %+.1f mm, %d zero crossings" % (h150[-1], crossings(h150)))
check("200 ms delay no longer settles", not settled(h200, tol=15.0),
      "final %+.1f mm — re-derive the gains if the loop slows this far" % h200[-1])
check("ringing grows with delay before stability is lost",
      crossings(h150) > crossings(simulate(120.0, 0.0, kp=0.05, kd=0.07,
                                           delay_s=0.05, seconds=12.0)),
      "%d crossings at 150 ms vs %d at 50 ms"
      % (crossings(h150),
         crossings(simulate(120.0, 0.0, kp=0.05, kd=0.07, delay_s=0.05, seconds=12.0))))

print("\nOff-target tracking")
h = simulate(0.0, 0.0, kp=0.05, kd=0.07, target=100.0)
err = abs(h[-1] - 100.0)
check("drives to a non-zero target", err < 12.0, "final %+.1f mm (target 100)" % h[-1])

print("\nTilt clamp")
h = simulate(350.0, 0.0, kp=0.5, kd=0.7, max_tilt=1.0)
check("survives a hard clamp without diverging", max(abs(v) for v in h) <= 400.0,
      "peak %.0f mm" % max(abs(v) for v in h))

# ---------------------------------------------------------------------------
# Slew limit. It exists because an unlimited command could swing the full tilt
# range inside a single move, which throws the ball off instead of steering it.
# But it is a limit on control authority, so it can be set low enough to stop
# the loop settling at all -- and that failure looks like sluggishness, not
# like a misconfiguration. These pin the usable range.
# ---------------------------------------------------------------------------
print("\nSlew limit")
SHIPPED = 25.0

for label, kwargs in (("released 120 mm off centre", dict(x0=120.0, v0=0.0)),
                      ("struck at 400 mm/s", dict(x0=0.0, v0=400.0)),
                      ("with 1.5 mm of noise", dict(x0=120.0, v0=0.0, noise=1.5))):
    h = simulate(kp=0.05, kd=0.07, delay_s=0.15, seconds=16.0, max_tilt=3.0,
                 slew=SHIPPED, **kwargs)
    check("the shipped %g deg/s limit still settles: %s" % (SHIPPED, label),
          settled(h, tol=15.0), "final %+.1f mm" % h[-1])

h_slow = simulate(120.0, 0.0, kp=0.05, kd=0.07, delay_s=0.15, seconds=16.0,
                  max_tilt=3.0, slew=12.0, noise=1.5)
check("but too tight a limit stops it settling at all", not settled(h_slow, tol=15.0),
      "12 deg/s -> still swinging %+.0f to %+.0f mm at the end, not resting"
      % (min(h_slow[-80:]), max(h_slow[-80:])))

# The point of the limit is the acceleration that lifts the ball off the plate.
# Tilting pivots the plate about its middle, so that acceleration depends on
# where the ball IS: at the rim it is largest, near the centre almost nothing.
# Sizing the limit from the rim -- which this test used to do -- is about three
# times stricter than the ball ever experiences while the loop is holding it,
# and that over-strictness is what kept the tilt rate too low to damp the orbit.
MOVE_TIME = 0.10          # matches mod_balance_move_time
WORKING_MM = 60.0         # the loop holds the ball within about this


def lift_g(deg_per_move, radius_mm, move_time=MOVE_TIME):
    travel = radius_mm * math.sin(math.radians(deg_per_move)) / 1000.0
    return math.pi ** 2 * travel / (2.0 * move_time ** 2) / 9.81


per_move = SHIPPED * MOVE_TIME
check("the shipped rate is gentle where the ball actually sits",
      lift_g(per_move, WORKING_MM) < 0.5,
      "%.1f deg per move: %.2f g at %.0f mm out" % (per_move,
      lift_g(per_move, WORKING_MM), WORKING_MM))
check("and still under 1 g even out at the rim",
      lift_g(per_move, 149.5) < 1.0,
      "%.2f g at the rim" % lift_g(per_move, 149.5))
# The limit was introduced when the clamp was 5 deg, where an unlimited swing
# really did throw the ball. With the clamp now 3 deg the clamp alone keeps the
# rim under 1 g, so the rate limit is no longer what stands between the ball
# and being launched -- it earns its place by damping instead. Worth stating
# plainly rather than leaving a stale claim that the numbers no longer support.
check("the old 5 deg clamp is what an unlimited swing could throw",
      lift_g(10.0, 149.5) > 1.0,
      "5 deg swung end to end: %.2f g" % lift_g(10.0, 149.5))
check("the 3 deg clamp alone now stays under 1 g even unlimited",
      lift_g(6.0, 149.5) < 1.0,
      "3 deg swung end to end: %.2f g" % lift_g(6.0, 149.5))

# ---------------------------------------------------------------------------
# Losing sight of the ball. The camera band is much narrower than the plate, so
# a ball can be on the plate and invisible; what the loop does in that moment
# decides whether the run continues or ends there.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# The camera rate. Everything above feeds the velocity estimator once per
# simulation step, which is 100 Hz -- and that is NOT what the machine does.
# The camera was measured at 30 fps, every format and every requested rate, so
# the estimator gets a third of the samples and the velocity it returns is
# correspondingly later. Simulating at 100 Hz made the loop look far better
# than it is and produced gains that oscillated on the bench. This section
# runs at the real rate.
# ---------------------------------------------------------------------------
print("\nAt the camera's real 30 fps")
CAM_HZ = 30.0


def realistic(kp, kd, ki, window, move_time, x0=60.0, v0=0.0, slope=1.4,
              cam_hz=CAM_HZ, secs=25.0, dt=0.001, max_tilt=3.0, slew=25.0,
              noise=1.0, clamp=20.0, seed=3):
    """Plant at 1 ms, measurements at the camera rate, commands at the move rate."""
    import random
    rng = random.Random(seed)
    pid, est = PIDAxis(), VelocityEstimator(window=window)
    x, v, t = x0, v0, 0.0
    cmd_t, cam_t, held, tilt = -9.0, -9.0, 0.0, 0.0
    pipe, hist, vx = deque(), [], 0.0
    delay = move_time + 0.05                    # the firmware's own margin
    while t < secs:
        if t - cam_t >= 1.0 / cam_hz:
            cam_t = t
            est.add(t, x + rng.gauss(0.0, noise), 0.0)
            vx, _ = est.estimate()
        if t - cmd_t >= move_time:
            cmd_t = t
            u = max(-max_tilt, min(max_tilt,
                                   pid.step(x, vx, kp, ki, kd, clamp, t)))
            step = slew * move_time
            held += max(-step, min(step, u - held))
            pipe.append((t + delay, held))
        while pipe and pipe[0][0] <= t:
            tilt = pipe.popleft()[1]
        v += C_ROLL * G * math.sin(math.radians(tilt + slope)) * dt
        x += v * dt
        if abs(x) > 400.0:
            hist.append(x)
            break
        t += dt
        hist.append(x)
    return hist


def residual(h):
    """Offset and peak-to-peak over the last stretch."""
    if abs(h[-1]) >= 400.0:
        return None
    tail = h[-8000:]
    return abs(sum(tail) / len(tail)), max(tail) - min(tail)


shipped = residual(realistic(0.020, 0.040, 0.10, 6, 0.06))
check("the shipped gains settle at the real camera rate",
      shipped is not None and shipped[1] < 12.0,
      "swing %.1f mm, offset %.1f mm" % (shipped[1], shipped[0]) if shipped else "LOST")

old = residual(realistic(0.050, 0.070, 0.10, 6, 0.10))
check("the gains derived at 100 Hz do NOT",
      old is None or old[1] > 20.0,
      "kp .05 kd .07 move .10 -> swing %.1f mm" % old[1] if old else "LOST")

slow = residual(realistic(0.020, 0.040, 0.10, 6, 0.06, cam_hz=20.0))
check("and they hold up if the camera drops to 20 fps",
      slow is not None and slow[1] < 20.0,
      "swing %.1f mm" % slow[1] if slow else "LOST")

# the velocity window is counted in SAMPLES, so its lag depends on the rate
long_win = residual(realistic(0.020, 0.040, 0.10, 16, 0.06))
check("too long a velocity window is lag, not smoothing",
      long_win is None or long_win[1] > shipped[1] * 1.5,
      "window 16 (0.53 s at 30 fps) -> swing %.1f mm"
      % long_win[1] if long_win else "LOST")

print("\nWhen the ball goes out of sight")
MM_PER_PX, BAND_PX = 0.20, 140.0


def escape(recover_s, recover_deg, v0, slope=1.4, secs=16.0, dt=0.01,
           delay=0.15, kp=0.05, kd=0.07, ki=0.10, clamp=20.0, max_tilt=3.0,
           slew=25.0, noise=1.0, seed=4):
    """Ball leaves the visible band at v0; does the plate get it back?"""
    import random
    rng = random.Random(seed)
    pid, est = PIDAxis(), VelocityEstimator(window=6)
    x, v, last, t = 0.0, v0, 0.0, 0.0
    pipe = deque([0.0] * max(1, int(round(delay / dt))))
    last_seen, hist = None, []
    while t < secs:
        px = x / MM_PER_PX
        if abs(px) <= BAND_PX:
            m = x + rng.gauss(0.0, noise)
            est.add(t, m, 0.0)
            vx, _ = est.estimate()
            u = pid.step(m, vx, kp, ki, kd, clamp, t)
            last_seen = (px, t)
        elif last_seen is not None and recover_s > 0 and t - last_seen[1] < recover_s:
            u = -recover_deg * (1.0 if last_seen[0] > 0 else -1.0)
        else:
            u = 0.0
            pid.reset()
            est.reset()
        u = max(-max_tilt, min(max_tilt, u))
        step = slew * dt
        u = last + max(-step, min(step, u - last))
        last = u
        pipe.append(u)
        applied = pipe.popleft()
        v += C_ROLL * G * math.sin(math.radians(applied + slope)) * dt
        x += v * dt
        if abs(x) > 400.0:
            hist.append(x)
            break
        t += dt
        hist.append(x)
    return hist


def recovered(h):
    return abs(h[-1]) < 30.0


check("levelling on a lost ball loses it, even on a slow drift",
      not recovered(escape(0.0, 0.0, 40.0)),
      "40 mm/s with no recovery -> %+.0f mm" % escape(0.0, 0.0, 40.0)[-1])
check("the shipped recovery gets that one back",
      recovered(escape(1.5, 2.5, 40.0)),
      "40 mm/s -> %+.0f mm" % escape(1.5, 2.5, 40.0)[-1])
check("and a considerably faster one",
      recovered(escape(1.5, 2.5, 100.0)),
      "100 mm/s -> %+.0f mm" % escape(1.5, 2.5, 100.0)[-1])
check("leaning harder is worse, not better",
      not recovered(escape(1.5, 3.0, 100.0)),
      "3.0 deg hauls it back through the middle and out the far side")
check("recovery leaves a ball that never left alone",
      recovered(escape(1.5, 2.5, 0.0)),
      "final %+.1f mm" % escape(1.5, 2.5, 0.0)[-1])

print("\n%s" % ("ALL CHECKS PASSED" if not FAILED else "FAILURES: " + ", ".join(FAILED)))
sys.exit(1 if FAILED else 0)
