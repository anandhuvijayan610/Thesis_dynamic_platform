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
import optics

MANUAL = "Manual"
BALANCING = "Balancing"
BALANCE_REST = "Balance then rest"
BALANCE_JUGGLE = "Balance and juggle"
JUGGLING = "Juggling"
ROUTINE = "Juggle routine"

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
        self._last_ball_t = 0.0
        self._plate_high = False
        self._suspend_reason = ""
        self._saved_gains = None
        self._saved_target = None
        self._recovery_gains = None
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
        # Seen "just now" at the start, so the very first cycle is not judged
        # against a stale timestamp from a previous run.
        self._last_ball_t = now
        self._plate_high = False
        self._suspend_reason = ""
        self._recovery_gains = None
        self._phase = "starting"
        self._last_gain_write = 0.0
        # Remember the gains before touching them, so stopping always puts the
        # user's own tuning back however the run ended.
        self._saved_gains = ({k: self._p.get(k) for k in GAIN_KEYS}
                             if mode == BALANCE_REST else None)
        # Same for the target: the routine walks it around, and a run that
        # ended anywhere but the middle would otherwise leave every later mode
        # quietly balancing to an off-centre point.
        self._saved_target = ((self._p.get("ctl_target_x"),
                               self._p.get("ctl_target_y"))
                              if mode == ROUTINE else None)

    def stop(self) -> None:
        self._restore_gains()
        self._restore_recovery_gains()
        self._restore_target()
        self._mode = MANUAL
        self._phase = ""

    def _use_recovery_gains(self, now: float) -> None:
        """Swap in the gains that stop a ball, remembering the run's own."""
        if self._recovery_gains is None:
            self._recovery_gains = {k: self._p.get(k) for k in GAIN_KEYS}
        if now - self._last_gain_write < GAIN_WRITE_INTERVAL:
            return
        self._last_gain_write = now
        for live, target in (("pid_kp_x", "mod_rest_kp"), ("pid_kp_y", "mod_rest_kp"),
                             ("pid_kd_x", "mod_rest_kd"), ("pid_kd_y", "mod_rest_kd"),
                             ("ctl_vel_window", "mod_rest_window")):
            self._p.set(live, self._p.get(target))

    def _restore_recovery_gains(self) -> None:
        """Put the run's own gains back the moment juggling resumes."""
        if self._recovery_gains is not None:
            for key, value in self._recovery_gains.items():
                self._p.set(key, value)
            self._recovery_gains = None

    def _restore_target(self) -> None:
        if self._saved_target is not None:
            self._p.set("ctl_target_x", self._saved_target[0])
            self._p.set("ctl_target_y", self._saved_target[1])
            self._saved_target = None

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

    # -- the routine's script ---------------------------------------------
    def _routine_waypoint(self, origin: float):
        """Where the target should be, given how many cycles have run.

        Returns (x_mm, y_mm, stage) or None once the choreography is finished.

        The whole routine is expressed as a target that moves; the juggle cycle
        underneath never changes. That is the difference between this and the
        Unity demo it is modelled on: that one aims each individual bounce and
        needs the ball's measured height and flight time to do it, neither of
        which this host has. Moving the target instead asks the PID loop to do
        something it is already doing well, and costs no new measurement.
        """
        warm = int(self._p.get("mod_rou_warmup_cycles"))
        leg = max(1, int(self._p.get("mod_rou_leg_cycles")))
        walk = self._p.get("mod_rou_walk_mm")
        pts = max(3, int(self._p.get("mod_rou_circle_points")))
        per = max(1, int(self._p.get("mod_rou_circle_cycles")))
        radius = self._p.get("mod_rou_circle_mm")
        rest = int(self._p.get("mod_rou_settle_cycles"))

        done = self._cycles

        if done < warm:
            return 0.0, 0.0, "warming up %d/%d" % (done, warm)
        done -= warm

        # Out and back on each axis in turn. Both axes, because the camera's
        # two axes do not run out at the same distance and a routine that only
        # ever moved in X would never exercise the tighter one.
        legs = [(walk, 0.0), (0.0, 0.0), (-walk, 0.0), (0.0, 0.0),
                (0.0, walk), (0.0, 0.0), (0.0, -walk), (0.0, 0.0)]
        if done < leg * len(legs):
            i = done // leg
            x, y = legs[i]
            return x, y, "walking %d/%d" % (i + 1, len(legs))
        done -= leg * len(legs)

        if done < per * pts:
            i = done // per
            angle = 2.0 * math.pi * i / pts
            return (radius * math.cos(angle), radius * math.sin(angle),
                    "circle %d/%d" % (i + 1, pts))
        done -= per * pts

        if done < rest:
            return 0.0, 0.0, "settling %d/%d" % (done, rest)

        return None

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
                # Use the RESTING gains while centring, not the juggling ones.
                #
                # The juggling pair keeps the ball circling the middle - a limit
                # cycle the loop's own delay sustains - and a circling ball has
                # a roughly constant speed, so it never satisfies the "slow
                # enough" half of the test below and centring never completes.
                # Measured on a real run: 13.8 s of the ball orbiting between 50
                # and 200 px out, never once settling.
                #
                # This is the same trade Balance-then-rest makes, and the same
                # gains: softer proportional, longer velocity window, which
                # turns the circle into a stop. Slower to catch a ball that is
                # moving, which does not matter here because catching is exactly
                # what has already failed.
                self._use_recovery_gains(now)
                move = self._p.get("mod_balance_move_time")
                self._phase = ("centring %d/%d" % (self._centre_streak, hold)
                               if ball is not None else "centring - no ball")
                if self._suspend_reason:
                    # Keep saying WHY the juggle stopped for as long as it is
                    # stopped. Without this the reason showed for a single
                    # command and was then overwritten by the centring counter,
                    # so a run that suspended on drift looked identical to one
                    # that had simply not started yet.
                    self._phase += " (suspended: %s)" % self._suspend_reason
                self._next_send = now + move
                return Command(low, move, allow_tilt=True, phase=self._phase)

            self._centred = True
            self._suspend_reason = ""
            self._restore_recovery_gains()
            self._last_ball_t = now

        # Keep juggling only while the ball is both THERE and still in the
        # middle of what the camera can see.
        #
        # Without this the cycle ran on the clock alone: once it started it
        # never looked at the ball again, and a recorded run spent four seconds
        # throwing an empty plate after the ball had rolled out of frame.
        #
        # Suspending is also the strongest correction available. Tilt cannot
        # move a ball that is in the air, so while juggling the loop only has
        # the contact phases - 87% of the cycle. Stopping the throw hands it the
        # whole cycle, at the bottom of the stroke, with the plate still.
        #
        # Dropping _centred is all it takes: that state IS "balance at the
        # bottom and wait", and the gate above already implements it, announces
        # itself, and will not resume until the ball is settled. The two
        # thresholds deliberately differ - out past mod_jug_keep_mm, back within
        # mod_jug_centre_px - so it cannot chatter across a single boundary.
        ball = self._state
        if ball is not None:
            self._last_ball_t = now

        lost_for = now - self._last_ball_t
        keep_px = self._p.get("mod_jug_keep_mm") * optics.px_per_mm(1000.0 * low)
        adrift = ball is not None and math.hypot(ball.x, ball.y) > keep_px

        if lost_for > self._p.get("mod_jug_lost_seconds") or adrift:
            self._centred = False
            self._centre_streak = 0
            if self._mode == ROUTINE:
                # Recover to the middle of the frame, not to whichever waypoint
                # the choreography had walked out to - the constraint being
                # escaped is the camera's, and that is centred on the frame.
                # _cycles is left alone so the routine resumes where it was.
                self._p.set("ctl_target_x", 0.0)
                self._p.set("ctl_target_y", 0.0)

            self._suspend_reason = (
                "ball %.0f px out of frame" % math.hypot(ball.x, ball.y) if adrift
                else "ball not seen for %.1f s" % lost_for)
            self._phase = "suspended - " + self._suspend_reason

            # Come down before handing over. The gate below moves at the
            # balancing move time, and from the top of the stroke that is 16 mm
            # in 0.06 s - about 2.2 g, which drops the plate out from under the
            # ball rather than catching it. Two of the four phase boundaries
            # leave the plate up here.
            if self._plate_high:
                fall = self._p.get("mod_jug_fall_time")
                self._plate_high = False
                self._next_send = now + max(fall, machine.MOVE_DURATION_FLOOR) + PHASE_MARGIN
                return Command(low, fall, allow_tilt=True, phase=self._phase)

            move = self._p.get("mod_balance_move_time")
            self._next_send = now + move
            return Command(low, move, allow_tilt=True, phase=self._phase)

        # The routine rides on this same cycle and only steers the target.
        # Written into the live store, the way BALANCE_REST writes its gains,
        # so the control loop needs to know nothing about the choreography;
        # stop() puts the target back.
        stage = ""
        if self._mode == ROUTINE:
            point = self._routine_waypoint(origin)
            if point is None:
                # Script finished. Stop oscillating and hold at the bottom of
                # the stroke so the ball comes to rest on a still plate, rather
                # than ending mid-throw.
                self._p.set("ctl_target_x", 0.0)
                self._p.set("ctl_target_y", 0.0)
                move = self._p.get("mod_balance_move_time")
                self._phase = "landed - %d cycles" % self._cycles
                self._next_send = now + move
                return Command(low, move, allow_tilt=True, phase=self._phase)

            x_mm, y_mm, stage = point
            # Waypoints are in millimetres because that is what the plate and
            # the camera window are measured in; the loop wants pixels.
            scale = optics.px_per_mm(1000.0 * low)
            self._p.set("ctl_target_x", x_mm * scale)
            self._p.set("ctl_target_y", y_mm * scale)

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
        self._plate_high = height > low + 1e-9
        self._phase = "%s - %s" % (stage, name) if stage else name
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
