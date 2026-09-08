"""Session modes: what height the plate should hold, and when to say so.

The control loop decides the tilt. This decides the height, the move time, and
whether a tilt is allowed yet — which together are what separate "balancing"
from "juggling" from doing nothing.

The awkward part is timing, and it is a property of the firmware rather than a
design choice. Every line received makes the firmware clear its queued batches
and restart, and each move is a half-cosine that begins at rest. Re-sending
"go to 40 mm in 0.8 s" on every control tick therefore restarts that profile
from zero velocity every few milliseconds and the plate crawls instead of
rising. So a mode has to say *when* it wants to speak, not only what to say,
and a long move must be sent once and then left alone until it has finished.

Nothing here touches the serial port or Qt; it is a clock and some arithmetic,
which is what makes it testable without hardware.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import machine

MANUAL = "Manual"
BALANCING = "Balancing"
BALANCE_REST = "Balance then rest"
BALANCE_JUGGLE = "Balance and juggle"
JUGGLING = "Juggling"

# Gains that hold the ball are not the gains that let it stop. The shipped pair
# keeps the ball circling the middle -- a limit cycle the loop's own delay
# sustains, which no amount of damping removes at that delay. Softening the
# proportional gain and lengthening the velocity window turns the circle into a
# stop, at the cost of being slower to catch a ball that is moving. So the run
# uses one set, the rest uses the other, and it blends between them.
GAIN_KEYS = ("pid_kp_x", "pid_kp_y", "pid_kd_x", "pid_kd_y",
             "pid_ki_x", "pid_ki_y", "ctl_vel_window")
GAIN_WRITE_INTERVAL = 0.1     # do not repaint the parameter widgets every tick

# Wall-clock slack added to a move before the next one is sent. The firmware
# needs to actually finish; without it each phase is cut short by scheduling
# jitter and the rhythm drifts.
PHASE_MARGIN = 0.02


@dataclass
class Command:
    """One pose to send, and what the mode is doing at the time."""
    height_m: float
    move_time: float
    allow_tilt: bool
    phase: str


class ModeRunner:
    """Height profile for the current mode. Ask it on every control tick."""

    def __init__(self, params) -> None:
        self._p = params
        self._mode = MANUAL
        self._t0 = 0.0
        self._next_send = 0.0
        self._phase = ""
        self._step = 0
        self._cycles = 0
        self._centred = False
        self._centre_streak = 0
        self._state = None
        self._saved_gains = None
        self._last_gain_write = 0.0
        self._hop_step = 0
        self._last_hop = 0.0
        self._hops = 0

    # -- state -----------------------------------------------------------
    @property
    def mode(self) -> str:
        return self._mode

    @property
    def phase(self) -> str:
        return self._phase

    @property
    def running(self) -> bool:
        return self._mode != MANUAL

    @property
    def cycles(self) -> int:
        """Completed juggle cycles, for the readout."""
        return self._cycles

    @property
    def hops(self) -> int:
        """Hops thrown so far in the balance-and-juggle mode."""
        return self._hops

    def start(self, mode: str, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        self._mode = mode
        self._t0 = now
        self._next_send = now          # the first command is due immediately
        self._step = 0
        self._cycles = 0
        self._hop_step = 0
        self._hops = 0
        self._last_hop = now
        self._centred = False
        self._centre_streak = 0
        self._phase = "starting"
        self._last_gain_write = 0.0
        # Remember the gains before touching them, so stopping always puts the
        # user's own tuning back however the run ended.
        self._saved_gains = ({k: self._p.get(k) for k in GAIN_KEYS}
                             if mode == BALANCE_REST else None)

    def stop(self) -> None:
        self._restore_gains()
        self._mode = MANUAL
        self._phase = ""

    def _restore_gains(self) -> None:
        if self._saved_gains is not None:
            for key, value in self._saved_gains.items():
                self._p.set(key, value)
            self._saved_gains = None

    def _blend_gains(self, now: float, fraction: float) -> None:
        """Move the gains a fraction of the way toward the resting set.

        Written into the live parameter store rather than passed down, because
        that store is what the control loop already reads every tick -- and it
        means the change is visible on the Control tab while it happens, rather
        than being a hidden second set of numbers.
        """
        if self._saved_gains is None:
            return
        if now - self._last_gain_write < GAIN_WRITE_INTERVAL and fraction < 1.0:
            return
        self._last_gain_write = now
        f = max(0.0, min(1.0, fraction))
        targets = (("pid_kp_x", "mod_rest_kp"), ("pid_kp_y", "mod_rest_kp"),
                   ("pid_kd_x", "mod_rest_kd"), ("pid_kd_y", "mod_rest_kd"),
                   ("pid_ki_x", "mod_rest_ki"), ("pid_ki_y", "mod_rest_ki"),
                   ("ctl_vel_window", "mod_rest_window"))
        for live, target in targets:
            start = self._saved_gains[live]
            self._p.set(live, start + f * (self._p.get(target) - start))

    # -- the one call that matters ---------------------------------------
    def command(self, now: Optional[float] = None,
                state=None) -> Optional[Command]:
        """The pose to send now, or None when nothing is due yet.

        Returning None is not idleness — it is the mode declining to interrupt
        a move that is still running.
        """
        now = time.monotonic() if now is None else now
        self._state = state
        if self._mode == MANUAL or now < self._next_send:
            return None
        origin = self._p.get("mac_origin_offset") / 1000.0
        if self._mode in (BALANCING, BALANCE_REST):
            return self._balancing(now, origin)
        if self._mode == BALANCE_JUGGLE:
            return self._balance_juggle(now, origin)
        return self._juggling(now, origin)

    # -- balancing --------------------------------------------------------
    def _balancing(self, now: float, origin: float) -> Command:
        """Rise once, settle, then hold that height and tilt.

        The rise is deliberately a single command. Tilting during it would be
        working against a plate that is still moving vertically, and the ball
        has nothing useful to tell us until the platform is where it belongs.
        """
        rise = self._p.get("mod_rise_time")
        settle = self._p.get("mod_settle_time")
        height = origin + self._p.get("mod_balance_height") / 1000.0

        if now - self._t0 < rise + settle:
            self._phase = "rising to %.0f mm" % self._p.get("mod_balance_height")
            self._next_send = self._t0 + rise + settle
            return Command(height, rise, allow_tilt=False, phase=self._phase)

        move_time = self._p.get("mod_balance_move_time")
        self._next_send = now + move_time

        if self._mode == BALANCE_REST:
            held = now - self._t0 - (rise + settle)
            hold = self._p.get("mod_hold_seconds")
            blend = max(1e-6, self._p.get("mod_rest_blend"))
            if held < hold:
                self._blend_gains(now, 0.0)
                self._phase = "holding, %.0f s to go" % (hold - held)
            elif held < hold + blend:
                f = (held - hold) / blend
                self._blend_gains(now, f)
                self._phase = "settling (%.0f%%)" % (100.0 * f)
            else:
                self._blend_gains(now, 1.0)
                self._phase = "at rest"
        else:
            self._phase = "balancing"

        return Command(height, move_time, allow_tilt=True, phase=self._phase)

    # -- balance, with an occasional hop ----------------------------------
    def _balance_juggle(self, now: float, origin: float) -> Command:
        """Hold the ball centred, and every so often throw it a little.

        Continuous bouncing and continuous balancing pull in different
        directions: the first wants the plate moving, the second wants it
        still. Alternating gets both -- the ball is held in the middle most of
        the time, and the hop is short enough that it lands more or less where
        it left.

        The hop is sized from what was measured to work on this machine, not
        from the arithmetic. Commanded acceleration does not predict separation
        here: 20 mm in 0.08 s is a higher peak g than 30 mm in 0.10 s and does
        NOT lift the ball, because the shorter stroke gives the motors too
        little time to reach the speed asked for. Bigger and slower wins.

        Tilt stays live through every phase, including while the ball is in the
        air: the plate has to be in the right place when it lands, and levelling
        during the hop throws away the correction that would put it there.
        """
        rise = self._p.get("mod_rise_time")
        settle = self._p.get("mod_settle_time")
        base = origin + self._p.get("mod_balance_height") / 1000.0

        if now - self._t0 < rise + settle:
            self._phase = "rising to %.0f mm" % self._p.get("mod_balance_height")
            self._next_send = self._t0 + rise + settle
            self._last_hop = self._t0 + rise + settle
            return Command(base, rise, allow_tilt=False, phase=self._phase)

        if self._hop_step == 0:
            due = self._p.get("mod_hop_every") - (now - self._last_hop)
            if due > 0.0:
                move_time = self._p.get("mod_balance_move_time")
                self._phase = "balancing, hop in %.1f s" % due
                self._next_send = now + move_time
                return Command(base, move_time, allow_tilt=True, phase=self._phase)
            self._hop_step = 1

        top = base + self._p.get("mod_hop_mm") / 1000.0
        legs = ((top, self._p.get("mod_hop_rise"), "hop"),
                (top, self._p.get("mod_hop_hang"), "airborne"),
                (base, self._p.get("mod_hop_fall"), "catching"))
        height, move_time, name = legs[self._hop_step - 1]
        self._hop_step += 1
        if self._hop_step > len(legs):
            self._hop_step = 0
            self._last_hop = now
            self._hops += 1
        self._phase = name
        self._next_send = now + max(move_time, machine.MOVE_DURATION_FLOOR) + PHASE_MARGIN
        return Command(height, move_time, allow_tilt=True, phase=name)

    # -- juggling ---------------------------------------------------------
    def _juggling(self, now: float, origin: float) -> Command:
        """A four-phase cycle: fast rise, dwell, gentle fall, dwell.

        Only the rise needs to beat 1 g — that is what separates the ball. The
        fall launches nothing, so running it at the rise's speed would be pure
        structural excitation for no benefit, and the dwells give the frame
        time to stop ringing between strokes. A dwell is sent as a move to the
        height the plate is already at, so it genuinely holds still.

        Tilt is applied on every phase, including the fall and the bottom
        dwell. Those are when the ball is resting in contact with the plate,
        which makes them the phases where tilt can actually roll it toward the
        centre; levelling there would throw most of the correction away.
        """
        low = origin + self._p.get("mod_jug_low") / 1000.0
        high = origin + self._p.get("mod_jug_high") / 1000.0
        rise = self._p.get("mod_rise_time")
        settle = self._p.get("mod_settle_time")

        if now - self._t0 < rise + settle:
            self._phase = "rising to %.0f mm" % self._p.get("mod_jug_low")
            self._next_send = self._t0 + rise + settle
            return Command(low, rise, allow_tilt=False, phase=self._phase)

        # Do not start throwing a ball that is not settled in the middle.
        #
        # This used to be a fixed wait: rise, pause for mod_settle_time, then
        # oscillate wherever the ball happened to be. Watching a run back, the
        # ball began 250 px off centre, and nine cycles later it had walked out
        # of the camera's window and was gone - the plate was throwing it while
        # it was already on its way out, and the contact phases never had
        # enough authority to bring it back. Bouncing a ball that is not
        # centred does not centre it; it loses it.
        #
        # So the settle time is now a MINIMUM rather than the whole test. Until
        # the ball has actually been near the target and slow for a few
        # consecutive checks, this keeps balancing at the bottom of the stroke.
        # A ball that is not visible at all counts as not centred, which is the
        # safe reading: an unseen ball must never be thrown.
        if not self._centred:
            hold = int(self._p.get("mod_jug_centre_hold"))
            ball = self._state
            near = False
            if ball is not None:
                dx = ball.x - self._p.get("ctl_target_x")
                dy = ball.y - self._p.get("ctl_target_y")
                near = (math.hypot(dx, dy) <= self._p.get("mod_jug_centre_px")
                        and math.hypot(ball.vx, ball.vy)
                        <= self._p.get("mod_jug_centre_speed"))
            self._centre_streak = self._centre_streak + 1 if near else 0

            if self._centre_streak < hold:
                move = self._p.get("mod_balance_move_time")
                self._phase = ("centring %d/%d" % (self._centre_streak, hold)
                               if ball is not None else "centring - no ball")
                self._next_send = now + move
                return Command(low, move, allow_tilt=True, phase=self._phase)

            self._centred = True

        phases: List[Tuple[float, float, str]] = [
            (high, self._p.get("mod_jug_rise_time"), "rise"),
            (high, self._p.get("mod_jug_top_dwell"), "top dwell"),
            (low, self._p.get("mod_jug_fall_time"), "fall"),
            (low, self._p.get("mod_jug_bottom_dwell"), "bottom dwell"),
        ]
        height, move_time, name = phases[self._step % 4]
        if self._step % 4 == 3:
            self._cycles += 1
        self._step += 1
        self._phase = name
        self._next_send = now + max(move_time, machine.MOVE_DURATION_FLOOR) + PHASE_MARGIN
        return Command(height, move_time, allow_tilt=True, phase=name)

    # -- reporting --------------------------------------------------------
    def separation_g(self) -> float:
        """Peak acceleration of the juggle rise, in g.

        For a half-cosine of amplitude A over T the peak is pi^2*A/(2T^2), at
        the start and end of the stroke. Below 1 g nothing pulls the ball away
        from the plate and it simply rides up and down in contact, which looks
        exactly like a machine that is not working.
        """
        amplitude = (self._p.get("mod_jug_high") - self._p.get("mod_jug_low")) / 1000.0
        t = max(1e-6, self._p.get("mod_jug_rise_time"))
        return math.pi ** 2 * amplitude / (2.0 * t * t) / 9.81

    def cycle_time(self) -> float:
        """Wall-clock length of one juggle cycle, margins included."""
        return sum(max(self._p.get(k), machine.MOVE_DURATION_FLOOR) + PHASE_MARGIN
                   for k in ("mod_jug_rise_time", "mod_jug_top_dwell",
                             "mod_jug_fall_time", "mod_jug_bottom_dwell"))
