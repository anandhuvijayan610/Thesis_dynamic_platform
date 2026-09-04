"""Checks on the mode state machine. No hardware, no Qt, no real clock.

Time is injected, so the phase boundaries are examined exactly rather than
raced against. The behaviour that matters most here is the one that is easy to
get wrong and invisible when wrong: a long move must be commanded once and then
left alone. Re-sending it restarts the firmware's half-cosine from rest every
time, and the plate creeps upward at a few mm/s while the log looks perfect.
"""
from __future__ import annotations

import sys

import machine
import modes
from params import ParameterStore

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print("  %s  %s%s" % ("PASS" if ok else "FAIL", label,
                          ("   " + detail) if detail else ""))
    if not ok:
        FAILURES.append(label)


def runner(**overrides):
    p = ParameterStore()
    p.set("mac_origin_offset", 10.0)
    for key, value in overrides.items():
        p.set(key, value)
    return modes.ModeRunner(p), p


# ---------------------------------------------------------------------------
def test_idle() -> None:
    print("\nIdle")
    r, _ = runner()
    check("a fresh runner is in manual", r.mode == modes.MANUAL)
    check("manual commands nothing", r.command(0.0) is None)
    check("and is not running", not r.running)


def test_balancing() -> None:
    print("\nBalancing")
    r, p = runner(mod_balance_height=40.0, mod_rise_time=0.8,
                  mod_settle_time=0.5, mod_balance_move_time=0.10)
    r.start(modes.BALANCING, now=0.0)

    first = r.command(0.0)
    check("it starts by rising", first is not None and first.phase.startswith("rising"))
    check("to the working origin plus the balancing height",
          abs(first.height_m - 0.050) < 1e-12, "%.1f mm" % (first.height_m * 1000))
    check("over the configured rise time", abs(first.move_time - 0.8) < 1e-12)
    check("with no tilt while it climbs", not first.allow_tilt)

    # The one that matters. A half-cosine restarted every tick never arrives.
    resends = [r.command(t) for t in (0.01, 0.05, 0.2, 0.5, 0.9, 1.29)]
    check("the rise is not re-sent while it runs", all(c is None for c in resends),
          "%d re-sends" % sum(c is not None for c in resends))

    after = r.command(1.31)
    check("tilting begins once it has risen and settled",
          after is not None and after.phase == "balancing" and after.allow_tilt)
    check("and holds the same height", abs(after.height_m - 0.050) < 1e-12)
    check("with the move time the gains were derived against",
          abs(after.move_time - 0.10) < 1e-12)

    check("no second command inside one move time", r.command(1.35) is None)
    nxt = r.command(1.42)
    check("but one on the next interval", nxt is not None and nxt.allow_tilt)

    # cadence over a longer run
    t, count = 1.42, 0
    while t < 6.42:
        t += 0.01
        if r.command(t) is not None:
            count += 1
    check("it commands about ten times a second", 45 <= count <= 55,
          "%d in 5 s" % count)


def test_balancing_height_tracks_origin() -> None:
    print("\nBalancing height is relative")
    r, p = runner(mod_balance_height=40.0)
    r.start(modes.BALANCING, now=0.0)
    a = r.command(0.0).height_m
    p.set("mac_origin_offset", 20.0)
    r.start(modes.BALANCING, now=0.0)
    b = r.command(0.0).height_m
    check("moving the working origin moves the balancing height with it",
          abs((b - a) - 0.010) < 1e-12, "%.1f -> %.1f mm" % (a * 1000, b * 1000))


def test_juggling() -> None:
    print("\nJuggling")
    r, p = runner(mod_jug_low=20.0, mod_jug_high=45.0, mod_rise_time=0.8,
                  mod_settle_time=0.5, mod_jug_rise_time=0.10,
                  mod_jug_top_dwell=0.08, mod_jug_fall_time=0.22,
                  mod_jug_bottom_dwell=0.15)
    r.start(modes.JUGGLING, now=0.0)

    first = r.command(0.0)
    check("it climbs to the bottom of the stroke first",
          first.phase.startswith("rising") and abs(first.height_m - 0.030) < 1e-12,
          "%.1f mm" % (first.height_m * 1000))
    check("gently, and without tilt",
          abs(first.move_time - 0.8) < 1e-12 and not first.allow_tilt)

    # walk one full cycle
    t = 1.31
    seen = []
    while len(seen) < 8:
        c = r.command(t)
        if c is not None:
            seen.append(c)
        t += 0.005

    names = [c.phase for c in seen]
    check("the cycle is rise, top dwell, fall, bottom dwell",
          names[:4] == ["rise", "top dwell", "fall", "bottom dwell"], str(names[:4]))
    check("and it repeats", names[4:8] == names[:4])

    rise, top, fall, bottom = seen[:4]
    check("the rise goes to the top", abs(rise.height_m - 0.055) < 1e-12)
    check("the top dwell stays there", abs(top.height_m - rise.height_m) < 1e-12)
    check("the fall goes to the bottom", abs(fall.height_m - 0.030) < 1e-12)
    check("the bottom dwell stays there", abs(bottom.height_m - fall.height_m) < 1e-12)

    check("the fall is slower than the rise", fall.move_time > rise.move_time * 1.5,
          "%.2f s vs %.2f s" % (fall.move_time, rise.move_time))
    check("tilt is applied on every phase, contact phases included",
          all(c.allow_tilt for c in seen))
    check("a full cycle was counted", r.cycles >= 1, "%d" % r.cycles)


def test_balance_then_rest() -> None:
    """The hold-then-settle sequence, and that it puts the gains back.

    The mode writes gains into the live store as it runs, which is the part
    worth guarding: a run that ended without restoring them would silently
    leave the machine detuned for everything afterwards.
    """
    print("\nBalance then rest")
    r, p = runner(mod_balance_height=40.0, mod_rise_time=0.8, mod_settle_time=0.5,
                  mod_balance_move_time=0.10, mod_hold_seconds=30.0,
                  mod_rest_blend=3.0, mod_rest_kp=0.02, mod_rest_kd=0.05,
                  mod_rest_ki=0.10, mod_rest_window=16)
    p.set("pid_kp_x", 0.05); p.set("pid_kd_x", 0.07)
    p.set("pid_ki_x", 0.10); p.set("ctl_vel_window", 6)
    running = (p.get("pid_kp_x"), p.get("ctl_vel_window"))

    r.start(modes.BALANCE_REST, now=0.0)
    r.command(0.0)                              # the rise
    check("it rises first, like plain balancing", r.phase.startswith("rising"))

    c = r.command(1.4)
    check("then holds, and says how long is left",
          c is not None and "holding" in r.phase, r.phase)
    check("the running gains are untouched while holding",
          abs(p.get("pid_kp_x") - running[0]) < 1e-9
          and p.get("ctl_vel_window") == running[1],
          "kp %.3f window %d" % (p.get("pid_kp_x"), p.get("ctl_vel_window")))

    # walk to the middle of the blend
    t = 1.4
    while t < 1.3 + 30.0 + 1.5:
        t += 0.05
        r.command(t)
    check("it announces the settling", "settling" in r.phase, r.phase)
    mid_kp = p.get("pid_kp_x")
    check("the gains are part way across, not switched",
          0.02 < mid_kp < 0.05, "kp %.4f" % mid_kp)

    while t < 1.3 + 30.0 + 4.0:
        t += 0.05
        r.command(t)
    check("and it reaches rest", r.phase == "at rest", r.phase)
    check("with the resting gains fully applied",
          abs(p.get("pid_kp_x") - 0.02) < 1e-6
          and p.get("ctl_vel_window") == 16,
          "kp %.4f window %d" % (p.get("pid_kp_x"), p.get("ctl_vel_window")))
    check("the integral is kept, so it does not drift off centre",
          abs(p.get("pid_ki_x") - 0.10) < 1e-9)

    r.stop()
    check("stopping restores the gains the user had",
          abs(p.get("pid_kp_x") - running[0]) < 1e-9
          and p.get("ctl_vel_window") == running[1],
          "kp %.3f window %d" % (p.get("pid_kp_x"), p.get("ctl_vel_window")))

    # and plain Balancing must not touch them at all
    r2, p2 = runner()
    p2.set("pid_kp_x", 0.05)
    r2.start(modes.BALANCING, now=0.0)
    for t in (0.0, 2.0, 40.0, 90.0):
        r2.command(t)
    check("plain Balancing never rewrites the gains",
          abs(p2.get("pid_kp_x") - 0.05) < 1e-9)
    r2.stop()


def test_balance_and_juggle() -> None:
    """Balancing most of the time, with a hop thrown in every few seconds."""
    print("\nBalance and juggle")
    r, p = runner(mod_balance_height=40.0, mod_rise_time=0.8, mod_settle_time=0.5,
                  mod_balance_move_time=0.06, mod_hop_every=3.0, mod_hop_mm=30.0,
                  mod_hop_rise=0.10, mod_hop_hang=0.10, mod_hop_fall=0.20)
    r.start(modes.BALANCE_JUGGLE, now=0.0)
    check("it rises first", r.command(0.0).phase.startswith("rising"))

    c = r.command(1.4)
    check("then balances, saying when the next hop is due",
          c is not None and "balancing" in r.phase and c.allow_tilt, r.phase)
    check("at the balancing height", abs(c.height_m - 0.050) < 1e-12)

    # walk forward until the hop fires, collecting what it sends
    t, seen = 1.4, []
    while t < 12.0:
        t += 0.01
        cmd = r.command(t)
        if cmd is not None and cmd.phase in ("hop", "airborne", "catching"):
            seen.append(cmd)
        if len(seen) >= 6:
            break
    names = [c.phase for c in seen]
    check("the hop is throw, hang, catch", names[:3] == ["hop", "airborne", "catching"],
          str(names[:3]))
    check("it throws by rising above the balancing height",
          seen[0].height_m > 0.050, "%.0f mm" % (seen[0].height_m * 1000))
    check("holds that height while the ball is in the air",
          abs(seen[1].height_m - seen[0].height_m) < 1e-12)
    check("and comes back down to balance", abs(seen[2].height_m - 0.050) < 1e-12)
    check("the return is slower than the throw",
          seen[2].move_time > seen[0].move_time * 1.5,
          "%.2f s vs %.2f s" % (seen[2].move_time, seen[0].move_time))
    check("tilt stays live through the whole hop, air included",
          all(c.allow_tilt for c in seen))
    check("a hop was counted", r.hops >= 1, "%d" % r.hops)

    # Collect EVERY command, not just the hop ones, or the balancing in between
    # is invisible and the sequence looks like one hop running into the next.
    r3, _ = runner(mod_rise_time=0.8, mod_settle_time=0.5, mod_hop_every=2.0,
                   mod_balance_move_time=0.06, mod_hop_mm=30.0,
                   mod_hop_rise=0.10, mod_hop_hang=0.10, mod_hop_fall=0.20)
    r3.start(modes.BALANCE_JUGGLE, now=0.0)
    t, order = 0.0, []
    while t < 8.0:
        t += 0.01
        cmd = r3.command(t)
        if cmd is not None:
            kind = cmd.phase if cmd.phase in ("hop", "airborne", "catching") \
                else "balancing"
            if not order or order[-1] != kind:
                order.append(kind)
    check("it returns to balancing after each hop",
          "catching" in order
          and order[order.index("catching") + 1] == "balancing",
          " -> ".join(order[:6]))
    r3.stop()

    # the gap between hops must be what was asked for
    r2, p2 = runner(mod_rise_time=0.8, mod_settle_time=0.5, mod_hop_every=2.0,
                    mod_balance_move_time=0.06)
    r2.start(modes.BALANCE_JUGGLE, now=0.0)
    t, hop_times = 0.0, []
    while t < 9.0:
        t += 0.01
        cmd = r2.command(t)
        if cmd is not None and cmd.phase == "hop":
            hop_times.append(t)
    gaps = [b - a for a, b in zip(hop_times, hop_times[1:])]
    check("hops come at the interval asked for",
          gaps and all(1.8 < g < 2.9 for g in gaps),
          "gaps %s" % ", ".join("%.1f" % g for g in gaps))
    r2.stop()
    r.stop()


def test_separation() -> None:
    print("\nSeparation threshold")
    r, p = runner(mod_jug_low=20.0, mod_jug_high=45.0, mod_jug_rise_time=0.10)
    # peak = pi^2 * A / (2 T^2); 25 mm in 0.10 s
    check("the shipped stroke clears 1 g", r.separation_g() > 1.0,
          "%.2f g" % r.separation_g())
    p.set("mod_jug_rise_time", 0.30)
    check("a slow stroke does not, and is reported as such",
          r.separation_g() < 1.0, "%.2f g at 0.30 s" % r.separation_g())
    p.set("mod_jug_rise_time", 0.10)

    p.set("mod_jug_high", 22.0)
    check("a tiny stroke does not either", r.separation_g() < 1.0,
          "%.2f g for 2 mm" % r.separation_g())

    p.set("mod_jug_high", 45.0)
    # Computed from the parameters, not written out: hardcoding the four
    # durations makes this fail every time the juggle is retuned, which says
    # nothing about whether cycle_time is correct.
    expected = sum(max(p.get(k), machine.MOVE_DURATION_FLOOR)
                   for k in ("mod_jug_rise_time", "mod_jug_top_dwell",
                             "mod_jug_fall_time", "mod_jug_bottom_dwell"))
    expected += 4 * modes.PHASE_MARGIN
    check("cycle time is the sum of the phases plus their margins",
          abs(r.cycle_time() - expected) < 1e-9,
          "%.2f s, expected %.2f" % (r.cycle_time(), expected))


def test_stop() -> None:
    print("\nStopping")
    r, _ = runner()
    r.start(modes.BALANCING, now=0.0)
    r.command(0.0)
    r.stop()
    check("stopping returns to manual", r.mode == modes.MANUAL)
    check("and commands nothing further", r.command(99.0) is None)

    r.start(modes.JUGGLING, now=0.0)
    check("restarting resets the cycle count", r.cycles == 0)
    check("and starts from the rise again",
          r.command(0.0).phase.startswith("rising"))


if __name__ == "__main__":
    test_idle()
    test_balancing()
    test_balancing_height_tracks_origin()
    test_balance_then_rest()
    test_balance_and_juggle()
    test_juggling()
    test_separation()
    test_stop()
    print("\n%s" % ("ALL CHECKS PASSED" if not FAILURES
                    else "FAILED: " + ", ".join(FAILURES)))
    sys.exit(1 if FAILURES else 0)
