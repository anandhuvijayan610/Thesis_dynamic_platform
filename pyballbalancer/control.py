"""Velocity estimation and the two tilt controllers.

The control loop runs on its own thread at a fixed rate rather than once per
frame, so the command rate to the microcontroller stays steady even when the
vision pipeline stutters. It always acts on the most recent detection it has
seen.

When the ball goes out of sight the plate is NOT levelled straight away. The
camera covers a band far narrower than the plate, so a ball can be sitting on
it and simply be invisible, and levelling then lets any residual slope carry it
further away — measured, that loses the ball at every escape speed tried, even
a 40 mm/s drift. Instead the plate leans back toward where the ball was last
seen for a short while, and only levels once that has failed.
"""
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional, Tuple

from PyQt5.QtCore import QThread, pyqtSignal

from vision import Detection


@dataclass
class BallState:
    x: float
    y: float
    vx: float
    vy: float
    radius: float
    t: float


class VelocityEstimator:
    """Least-squares slope over a short window.

    Differencing two consecutive frames doubles the position noise and, at
    100 fps over a few pixels of travel, that noise dominates the signal. A
    straight-line fit over N samples averages it down while still tracking a
    genuinely accelerating ball.
    """

    def __init__(self, window: int = 6) -> None:
        self._buf: Deque[Tuple[float, float, float]] = deque(maxlen=max(2, window))

    def set_window(self, window: int) -> None:
        window = max(2, int(window))
        if window != self._buf.maxlen:
            self._buf = deque(self._buf, maxlen=window)

    def reset(self) -> None:
        self._buf.clear()

    def add(self, t: float, x: float, y: float) -> None:
        self._buf.append((t, x, y))

    def estimate(self) -> Tuple[float, float]:
        n = len(self._buf)
        if n < 2:
            return 0.0, 0.0
        t0 = self._buf[0][0]
        ts = [s[0] - t0 for s in self._buf]
        mean_t = sum(ts) / n
        var_t = sum((t - mean_t) ** 2 for t in ts)
        if var_t < 1e-12:
            return 0.0, 0.0
        mean_x = sum(s[1] for s in self._buf) / n
        mean_y = sum(s[2] for s in self._buf) / n
        vx = sum((t - mean_t) * (s[1] - mean_x) for t, s in zip(ts, self._buf)) / var_t
        vy = sum((t - mean_t) * (s[2] - mean_y) for t, s in zip(ts, self._buf)) / var_t
        return vx, vy


class PIDAxis:
    """One axis, with the integral clamped so a stuck ball cannot wind it up."""

    def __init__(self) -> None:
        self.integral = 0.0
        self._last_t: Optional[float] = None

    def reset(self) -> None:
        self.integral = 0.0
        self._last_t = None

    def step(self, err: float, vel: float, kp: float, ki: float, kd: float,
             clamp: float, t: float) -> float:
        dt = 0.0 if self._last_t is None else max(0.0, t - self._last_t)
        self._last_t = t
        if ki > 0.0 and dt > 0.0:
            # The clamp is the whole anti-windup story here. Conditional
            # integration was tried and made no measurable difference: the
            # case it was meant to protect -- a ball struck hard enough to
            # saturate the tilt -- fails identically with it, without it, and
            # with ki at zero, because that ball is simply travelling faster
            # than a 3 deg plate can arrest. It is an authority limit, not a
            # windup one, so the extra mechanism earned nothing.
            self.integral = max(-clamp, min(clamp, self.integral + err * dt))
        else:
            self.integral = 0.0
        # derivative comes from the estimated velocity rather than from
        # differencing the error, which would re-introduce the noise the
        # estimator just removed
        return -(kp * err) - (ki * self.integral) - (kd * vel)


def analytical_tilt(state: BallState, tx: float, ty: float,
                    restitution: float, flight: float, gain: float) -> Tuple[float, float]:
    """Mirror-law tilt.

    Treat the bounce as a specular reflection: for the ball to leave along
    v_out having arrived along v_in, the plate normal must bisect them. The
    normal is therefore proportional to (-v_in/|v_in| + v_out/|v_out|), and
    its horizontal components give the two tilt angles.
    """
    g = 9810.0                                   # px/s² is not meaningful, so work in mm/s²
    vz_in = -g * flight / 2.0                    # downward speed at contact
    vz_out = -vz_in * max(0.05, restitution)     # upward after the bounce

    vin = (state.vx, state.vy, vz_in)
    vout = ((tx - state.x) / flight, (ty - state.y) / flight, vz_out)

    def unit(v):
        n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
        return (0.0, 0.0, 1.0) if n < 1e-9 else (v[0] / n, v[1] / n, v[2] / n)

    ix, iy, iz = unit(vin)
    ox, oy, oz = unit(vout)
    nx, ny, nz = (-ix + ox), (-iy + oy), (-iz + oz)
    if abs(nz) < 1e-6:
        return 0.0, 0.0
    # tilt about each axis is the angle between the normal and vertical
    return (math.degrees(math.atan2(nx, nz)) * gain,
            math.degrees(math.atan2(ny, nz)) * gain)


class ControlLoop(QThread):
    """Fixed-rate loop turning the latest ball state into a tilt command."""

    tilt_command = pyqtSignal(float, float)             # degrees
    state_ready = pyqtSignal(object)                    # BallState|None
    rate_measured = pyqtSignal(float)

    STALE_AFTER = 0.25          # seconds without a detection before levelling

    def __init__(self, params) -> None:
        super().__init__()
        self._params = params
        self._running = False
        self._enabled = False
        self._latest: Optional[Tuple[Detection, float]] = None
        self._vel = VelocityEstimator()
        self._pid_x, self._pid_y = PIDAxis(), PIDAxis()
        # Last command actually issued, so the next one can be limited relative
        # to it rather than jumping straight to whatever the PID asks for.
        self._out_x, self._out_y = 0.0, 0.0
        self._last_out_t = 0.0
        # Where the ball was when it was last seen, so a brief loss of sight
        # can be leaned against instead of surrendered to.
        self._last_seen = None
        # Smoothed apparent radius, which is how far away the plate is. A
        # single frame's radius is noisy enough to modulate the gains audibly,
        # and the quantity is genuinely slow -- it only changes as the plate
        # moves -- so it is worth filtering hard.
        self._radius_avg = None

    # ------------------------------------------------------------------
    def on_detection(self, det: Optional[Detection], t: float) -> None:
        """Called from the camera thread; only ever replaces a reference."""
        if det is not None:
            self._latest = (det, t)

    def set_enabled(self, on: bool) -> None:
        self._enabled = bool(on)
        # Forget the timestamp, not the value: the next tick then measures one
        # nominal period rather than the whole idle gap, which would otherwise
        # buy a single very large slew step. The last command is deliberately
        # kept, so arming continues from the tilt the plate is actually holding.
        self._last_out_t = 0.0
        if not on:
            self._last_seen = None
            self._pid_x.reset()
            self._pid_y.reset()
            self._vel.reset()

    def stop(self) -> None:
        self._running = False
        self.wait(2000)

    # ------------------------------------------------------------------
    def run(self) -> None:
        self._running = True
        last_seen_t = -1.0
        ticks, window_start = 0, time.monotonic()

        while self._running:
            p = self._params.snapshot()
            period = 1.0 / max(1, int(p["ctl_rate_hz"]))
            tick_started = time.monotonic()

            self._vel.set_window(p["ctl_vel_window"])
            latest = self._latest
            state: Optional[BallState] = None

            if latest is not None:
                det, t = latest
                if t != last_seen_t:
                    last_seen_t = t
                    self._vel.add(t, det.x, det.y)
                fresh = (tick_started - t) <= self.STALE_AFTER
                if fresh:
                    vx, vy = self._vel.estimate()
                    state = BallState(det.x, det.y, vx, vy, det.radius, t)
                    if det.radius > 1.0:
                        self._radius_avg = (
                            det.radius if self._radius_avg is None
                            else 0.85 * self._radius_avg + 0.15 * det.radius)
                else:
                    self._vel.reset()

            self.state_ready.emit(state)

            if self._enabled and state is not None:
                tx, ty = self._compute(state, p, tick_started)
                self._last_seen = (state.x, state.y, tick_started)
            elif (self._enabled and self._last_seen is not None
                  and tick_started - self._last_seen[2]
                  < float(p["ctl_recover_seconds"])):
                # The ball has gone out of sight, not necessarily off the plate:
                # the camera covers a band far narrower than the plate, so a
                # ball can be sitting perfectly well on it and simply not be
                # visible. Levelling here is the worst thing to do -- on any
                # residual slope the plate then lets it keep going, and a
                # momentary loss becomes a permanent one. Lean the other way
                # instead, toward where it was last seen, and give it a chance
                # to come back into view.
                lx, ly, _ = self._last_seen
                reach = math.hypot(lx, ly)
                if reach > 1.0:
                    mag = float(p["ctl_recover_tilt"])
                    tx, ty = -mag * lx / reach, -mag * ly / reach
                    tx, ty = self._map_axes(tx, ty, p)
                else:
                    tx, ty = 0.0, 0.0
                self._pid_x.reset()
                self._pid_y.reset()
            else:
                tx, ty = 0.0, 0.0       # no ball, or disarmed: sit flat
                self._last_seen = None
                self._radius_avg = None
                self._pid_x.reset()
                self._pid_y.reset()

            limit = float(p["ctl_max_tilt"])
            tx = max(-limit, min(limit, tx))
            ty = max(-limit, min(limit, ty))

            # Slew limit. The clamp above bounds how FAR the plate may tilt;
            # this bounds how FAST the command may get there, which is the part
            # the ball feels. A tilt that jumps several degrees inside one move
            # swings the plate corner through millimetres in a tenth of a
            # second, and the vertical acceleration that implies is what flicks
            # the ball off the surface -- the plate is then throwing the ball
            # rather than steering it. Limiting the rate keeps the full tilt
            # authority for a ball that really is far off centre, while taking
            # the violence out of getting there.
            rate = float(p["ctl_slew_rate"])
            if rate > 0.0:
                dt = (tick_started - self._last_out_t) if self._last_out_t else period
                step = rate * max(0.0, min(dt, 0.5))
                tx = self._out_x + max(-step, min(step, tx - self._out_x))
                ty = self._out_y + max(-step, min(step, ty - self._out_y))
            self._last_out_t = tick_started
            self._out_x, self._out_y = tx, ty

            self.tilt_command.emit(tx, ty)

            ticks += 1
            now = time.monotonic()
            if now - window_start >= 0.5:
                self.rate_measured.emit(ticks / (now - window_start))
                ticks, window_start = 0, now

            slack = period - (now - tick_started)
            if slack > 0:
                self.msleep(int(slack * 1000))

    # ------------------------------------------------------------------
    def _compute(self, state: BallState, p, t: float) -> Tuple[float, float]:
        tgt_x, tgt_y = float(p["ctl_target_x"]), float(p["ctl_target_y"])

        if p["ctl_mode"].startswith("PID"):
            ax = self._pid_x.step(state.x - tgt_x, state.vx, p["pid_kp_x"],
                                  p["pid_ki_x"], p["pid_kd_x"], p["pid_i_clamp"], t)
            ay = self._pid_y.step(state.y - tgt_y, state.vy, p["pid_kp_y"],
                                  p["pid_ki_y"], p["pid_kd_y"], p["pid_i_clamp"], t)
        else:
            ax, ay = analytical_tilt(state, tgt_x, tgt_y, p["ana_restitution"],
                                     p["ana_flight_time"], p["ana_gain"])

        scale = self._height_scale(p)
        return self._map_axes(ax * scale, ay * scale, p)

    def _height_scale(self, p) -> float:
        """Undo the change in image scale as the plate moves.

        The gains are degrees per pixel, but what the ball obeys is degrees
        per millimetre, and the camera is close enough underneath the plate
        that the two diverge sharply over the working range: the same ball
        spans 111 px resting at the balancing height and 87 px at the top of
        the juggling stroke. Without this the loop quietly loses a fifth of
        its authority at exactly the moment the ball is moving fastest.

        The ball itself carries the conversion. It is a sphere of known size,
        so its apparent radius is the scale, and using it needs no lens
        constants and no faith in the plate having reached the height it was
        told to. It also degrades safely: if the radius is unmeasured or wild,
        the scale falls back to 1 and the behaviour is what it was before.
        """
        if not p["ctl_scale_by_radius"]:
            return 1.0
        r = self._radius_avg
        ref = float(p["ctl_ref_radius"])
        if r is None or r < 1.0 or ref < 1.0:
            return 1.0
        return max(0.5, min(2.0, ref / r))

    @staticmethod
    def _map_axes(ax, ay, p):
        """Camera axes onto plate axes.

        Shared, because the recovery lean has to travel through exactly the
        same mapping as the controller's own output -- a recovery that pushed
        the opposite way to the loop would be worse than not recovering at all.
        """
        if p["ctl_swap_axes"]:
            ax, ay = ay, ax
        if p["ctl_invert_x"]:
            ax = -ax
        if p["ctl_invert_y"]:
            ay = -ay
        return ax, ay
