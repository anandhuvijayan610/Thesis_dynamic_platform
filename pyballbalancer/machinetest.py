"""Checks on the kinematics and the wire format. No hardware needed.

The firmware ignores a line it cannot parse instead of complaining, so a
mistake here produces a machine that sits still and gives no reason. That is
the failure this file exists to catch.
"""
from __future__ import annotations

import math
import sys

import machine

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print("  %s  %s%s" % ("PASS" if ok else "FAIL", label,
                          ("   " + detail) if detail else ""))
    if not ok:
        FAILURES.append(label)


# ---------------------------------------------------------------------------
def test_round_trip() -> None:
    print("\nInverse kinematics")
    worst = 0.0
    for mm in range(0, 81, 2):
        target = mm / 1000.0 + machine.HEIGHT_ORIGIN
        theta = machine.joint1_rotation(target, 0.0)
        worst = max(worst, abs(machine.forward_height(theta) - target))
    check("forward(inverse(h)) == h over 0-80 mm", worst < 1e-9,
          "worst error %.3e mm" % (worst * 1000))

    angles = [machine.joint1_rotation(mm / 1000.0 + machine.HEIGHT_ORIGIN, 0.0)
              for mm in range(0, 81, 2)]
    check("angle increases with height", all(b > a for a, b in zip(angles, angles[1:])))

    threshold = math.sqrt(machine.L2 ** 2 - (machine.Q - machine.L1) ** 2)
    check("the branch change sits inside the working range",
          0.0 < threshold - machine.HEIGHT_ORIGIN < 0.080,
          "%.2f mm above the plate origin" % ((threshold - machine.HEIGHT_ORIGIN) * 1000))

    far = machine.joint1_rotation(0.400, 0.0)
    check("an unreachable height clamps instead of returning NaN", not math.isnan(far))


def test_tilt_symmetry() -> None:
    print("\nTilt")
    level = machine.arm_angles(0.020, 0.0, 0.0)
    check("a level plate puts all four arms at the same angle",
          max(level) - min(level) < 1e-12)

    xt = machine.arm_angles(0.020, 3.0, 0.0)
    check("an X tilt moves the X pair", abs(xt[0] - xt[1]) > 1e-3,
          "%.4f rad apart" % abs(xt[0] - xt[1]))
    check("an X tilt leaves the Y pair together", abs(xt[2] - xt[3]) < 1e-12)

    yt = machine.arm_angles(0.020, 0.0, 3.0)
    check("a Y tilt moves the Y pair", abs(yt[2] - yt[3]) > 1e-3)
    check("a Y tilt leaves the X pair together", abs(yt[0] - yt[1]) < 1e-12)

    # Mirror symmetry belongs to the plate, not to the arm angles. The map
    # from joint height to angle is curved, so +3 deg and -3 deg give angle
    # changes that differ by ~0.5% -- measured to scale as tilt squared, which
    # is the curvature and not an error. Checking the angles directly would
    # therefore fail a correct solver, so the check is made where the symmetry
    # actually has to hold: the heights the two arms are sent to.
    neg = machine.arm_angles(0.020, -3.0, 0.0)
    pos_h = [machine.forward_height(a, machine.width_difference_from_tilt(3.0))
             for a in xt[:2]]
    neg_h = [machine.forward_height(a, machine.width_difference_from_tilt(-3.0))
             for a in neg[:2]]
    check("the two tilt directions are mirror images of each other",
          abs(pos_h[0] - neg_h[1]) < 1e-12 and abs(pos_h[1] - neg_h[0]) < 1e-12,
          "%.2e" % max(abs(pos_h[0] - neg_h[1]), abs(pos_h[1] - neg_h[0])))
    check("tilting does not shift the plate up or down",
          abs((pos_h[0] + pos_h[1]) / 2.0 - machine.HEIGHT_ORIGIN - 0.020) < 1e-12,
          "%.4f mm" % (((pos_h[0] + pos_h[1]) / 2.0
                        - machine.HEIGHT_ORIGIN - 0.020) * 1000))

    # The one that actually matters on the bench: the pairs must be distinct
    # physical axes. If MOTOR_ORDER pairs them wrongly both tilts act the same
    # way and the plate looks like it is barely responding.
    check("the two tilt axes touch different motors",
          {0, 1} != {machine.MOTOR_ORDER[2], machine.MOTOR_ORDER[3]})


def test_wire_format() -> None:
    print("\nWire format")
    line = machine.serialize([(0.010, 0.0, 0.0, 0.5)])
    fields = line.split(":")
    check("one batch is six fields", len(fields) == 6, line)
    check("the first marker is 11", abs(float(fields[0]) - 11.0) < 1e-9)
    check("move time is carried through", abs(float(fields[5]) - 0.5) < 1e-9)

    multi = machine.serialize([(0.010, 0.0, 0.0, 0.4)] * 3)
    mf = multi.split(":")
    check("three batches are eighteen fields", len(mf) == 18)
    check("markers step by 11",
          [float(mf[i * 6]) for i in range(3)] == [11.0, 22.0, 33.0])

    short = machine.serialize([(0.010, 0.0, 0.0, 0.001)])
    check("a too-short move is raised to the firmware floor",
          abs(float(short.split(":")[5]) - machine.MOVE_DURATION_FLOOR) < 1e-9)

    origin = machine.serialize([(0.0, 0.0, 0.0, 0.5)])
    check("the origin pose sends four zeros",
          all(abs(float(v)) < 1e-9 for v in origin.split(":")[1:5]), origin)

    check("every field parses as a double",
          all(_is_double(f) for f in machine.serialize(
              [(0.030, 2.0, -2.0, 0.2)]).split(":")))

    check("no field is NaN or inf",
          not any(t in machine.serialize([(0.030, 2.0, -2.0, 0.2)]).lower()
                  for t in ("nan", "inf")))


def _is_double(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


def test_trim() -> None:
    """The mechanical levelling offset.

    The trap here is the origin subtraction. serialize() sends every angle as a
    difference from ORIGIN_ANGLES, so a trim folded into that constant as well
    would cancel itself out and the plate would never move — the same mistake
    the Unity host documents for its own origin offset.
    """
    print("\nLevelling trim")
    poses = [(0.020, 0.0, 0.0, 0.5)]

    check("zero trim changes nothing",
          machine.apply_trim(poses, 0.0, 0.0) == list(poses))

    trimmed = machine.apply_trim(poses, 1.5, -0.5)
    check("the trim is added to the commanded tilt",
          trimmed[0][1] == 1.5 and trimmed[0][2] == -0.5, str(trimmed[0][1:3]))
    check("and leaves height and move time alone",
          trimmed[0][0] == poses[0][0] and trimmed[0][3] == poses[0][3])

    check("it applies to every batch, not just the first",
          all(p[1] == 1.5 for p in machine.apply_trim(poses * 4, 1.5, 0.0)))

    # An X trim must move the X pair only: this rig's standing tilt is on that
    # pair, and a trim that leaked into the other axis would tilt the plate
    # somewhere new while appearing to level it.
    level = machine.arm_angles(0.020, 0.0, 0.0)
    tx = machine.arm_angles(*machine.apply_trim(poses, 1.0, 0.0)[0][:3])
    check("an X trim moves the X pair", abs(tx[0] - tx[1]) > 1e-4,
          "%.4f rad apart" % abs(tx[0] - tx[1]))
    check("an X trim leaves the Y pair untouched",
          abs(tx[2] - level[2]) < 1e-12 and abs(tx[3] - level[3]) < 1e-12)

    ty = machine.arm_angles(*machine.apply_trim(poses, 0.0, 1.0)[0][:3])
    check("a Y trim moves the Y pair only",
          abs(ty[2] - ty[3]) > 1e-4 and abs(ty[0] - level[0]) < 1e-12)

    # the whole point: a trimmed "level" command must not serialise to zeros
    flat = machine.serialize([(0.0, 0.0, 0.0, 0.5)])
    tilted = machine.serialize(machine.apply_trim([(0.0, 0.0, 0.0, 0.5)], 1.0, 0.0))
    check("a trimmed origin does not send the origin pose", flat != tilted)
    check("and the untrimmed origin still sends four zeros",
          all(abs(float(v)) < 1e-9 for v in flat.split(":")[1:5]))

    # sign: the trim must be able to go both ways, symmetrically about level
    plus = machine.arm_angles(*machine.apply_trim(poses, 0.5, 0.0)[0][:3])
    minus = machine.arm_angles(*machine.apply_trim(poses, -0.5, 0.0)[0][:3])
    check("the two trim directions are opposite",
          (plus[0] - level[0]) * (minus[0] - level[0]) < 0,
          "%+.5f vs %+.5f rad" % (plus[0] - level[0], minus[0] - level[0]))


def test_pulses() -> None:
    print("\nPulses")
    full = machine.pulses_for(2.0 * math.pi)
    check("a full turn is one revolution of pulses", full == machine.PULSES_PER_REV,
          "%d" % full)
    check("sign is preserved", machine.pulses_for(-0.1) == -machine.pulses_for(0.1))

    # A 2 deg tilt has to be worth enough pulses to actually move the arm; a
    # geared stepper that is commanded a fraction of a step simply will not.
    angles = machine.arm_angles(0.020, 2.0, 0.0)
    diff = angles[0] - machine.ORIGIN_ANGLES[0]
    check("a 2 deg tilt is a usable number of pulses",
          abs(machine.pulses_for(diff)) > 50, "%d pulses" % machine.pulses_for(diff))


def test_bench_sequence() -> None:
    """The exact sequence the Machine tab sends, checked as a whole."""
    print("\nBench sequence")
    origin = 0.010
    poses = [(origin, 0.0, 0.0, 0.5),
             (origin + 0.020, 0.0, 0.0, 0.5),
             (origin + 0.020, 2.0, 0.0, 0.5),
             (origin + 0.020, -2.0, 0.0, 0.5),
             (origin + 0.020, 0.0, 2.0, 0.5),
             (origin + 0.020, 0.0, -2.0, 0.5),
             (origin, 0.0, 0.0, 0.5)]
    for height, xt, yt, _t in poses:
        angles = machine.arm_angles(height, xt, yt)
        assert not any(math.isnan(a) for a in angles), (height, xt, yt)
    check("every pose in the bring-up sequence is solvable", True)

    line = machine.serialize(poses)
    check("the whole sequence fits one line under the 100-batch ceiling",
          len(poses) <= 100 and len(line.split(":")) == 6 * len(poses))

    # Rising through the branch change must not make the arms jump backwards.
    heights = [origin + mm / 1000.0 for mm in range(0, 61, 1)]
    first = [machine.arm_angles(h, 0.0, 0.0)[0] for h in heights]
    check("a slow climb through the branch change stays monotonic",
          all(b > a for a, b in zip(first, first[1:])))
    biggest = max(abs(b - a) for a, b in zip(first, first[1:]))
    check("no 1 mm step asks for a jump", biggest < 0.05,
          "largest step %.4f rad" % biggest)


if __name__ == "__main__":
    test_round_trip()
    test_tilt_symmetry()
    test_wire_format()
    test_trim()
    test_pulses()
    test_bench_sequence()
    print("\n%s" % ("ALL CHECKS PASSED" if not FAILURES
                    else "FAILED: " + ", ".join(FAILURES)))
    sys.exit(1 if FAILURES else 0)
