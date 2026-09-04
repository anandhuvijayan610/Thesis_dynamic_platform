"""Machine model: high-level pose -> four arm angles -> the firmware's wire format.

This is a port of the Unity host's kinematics, kept deliberately faithful so
the same firmware accepts commands from either. The wire format the Teensy
actually parses is colon-separated, one batch of six values:

    <marker>:<a0>:<a1>:<a2>:<a3>:<move_time>

with marker = 11.0 * batch_number (1-based), the four arm angles in RADIANS,
and move_time in seconds. Several batches may be concatenated in one line.
Angles are sent as a DIFFERENCE from the origin pose, because the firmware
treats its power-on position as zero.

Getting any of that wrong fails silently: the firmware's strtok/atof parse
yields zero batches and it simply does nothing, which is exactly what a
mismatched protocol looks like from outside.
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

# Geometry, from the Unity Constants. Metres.
PLATE_WIDTH = 0.299        # between opposing joints
Q = 0.070023               # motor axis to upper joint offset
L1 = 0.089                 # driven link
L2 = 0.080                 # coupler
HEIGHT_ORIGIN = 0.0566     # plate height above the motor shafts at rest

PULSES_PER_REV = 16576     # firmware Constants.h, for reporting only
MOVE_DURATION_FLOOR = 0.05  # firmware clamps anything shorter up to this

# Which computed arm goes to which physical driver. Identity was confirmed
# correct on this machine; a wrong pairing makes the two tilt axes act on the
# same physical direction and the plate barely moves.
MOTOR_ORDER: Tuple[int, int, int, int] = (0, 1, 2, 3)


def height_difference_from_tilt(tilt_deg: float) -> float:
    return math.sin(math.radians(tilt_deg)) * PLATE_WIDTH / 2.0


def width_difference_from_tilt(tilt_deg: float) -> float:
    half = PLATE_WIDTH / 2.0
    return math.cos(math.radians(tilt_deg)) * half - half


def joint1_rotation(target_y: float, offset_q: float) -> float:
    """Solve y = L1·sin(x) + sqrt(L2² − (q − L1·cos(x))²) for x.

    Both the square root and the arc-cosine have restricted domains, and a
    target beyond the arm's reach pushes them outside it. Unclamped that
    yields NaN rather than an exception, and NaN would travel all the way to
    an integer pulse count. Hence the two clamps.
    """
    q = Q + offset_q
    denom = 2.0 * L1 * L1 * (4.0 * q * q + 4.0 * target_y * target_y)
    if abs(denom) < 1e-18:
        return 0.0
    a1 = 1.0 / denom
    a2 = -L1 * q * (-4.0 * L1 * L1 + 4.0 * L2 * L2 - 4.0 * q * q - 4.0 * target_y * target_y)

    y2 = target_y * target_y
    inner = (-L1 ** 2 * q ** 4 * y2
             - 2.0 * L1 ** 2 * q ** 2 * y2 ** 2
             + 2.0 * L1 ** 4 * q ** 2 * y2
             + 2.0 * L1 ** 2 * L2 ** 2 * q ** 2 * y2
             - L1 ** 2 * y2 ** 3
             + 2.0 * L1 ** 4 * y2 ** 2
             + 2.0 * L1 ** 2 * L2 ** 2 * y2 ** 2
             - L1 ** 6 * y2
             - L1 ** 2 * L2 ** 4 * y2
             + 2.0 * L1 ** 4 * L2 ** 2 * y2)
    a3 = -4.0 * math.sqrt(max(0.0, inner))

    # Two-branch solution. The arc-cosine is symmetric about the height reached
    # at theta1 = 0, so below that the arm is on the descending branch and the
    # angle is negative; above it the ascending branch applies. Taking the
    # negative branch throughout round-trips correctly only up to that height
    # and then silently returns a wrong, lower angle — which on this machine
    # means every commanded height above about 21 mm drives the plate somewhere
    # else entirely.
    local_max = math.sqrt(max(0.0, L2 * L2 - (q - L1) ** 2))
    acos_arg = max(-1.0, min(1.0, a1 * (a2 - a3)))
    return -math.acos(acos_arg) if target_y < local_max else math.acos(acos_arg)


def arm_angles(height_m: float, x_tilt_deg: float, y_tilt_deg: float) -> List[float]:
    """Four arm rotations, radians, for a plate pose.

    Arms 0/1 form the X tilt pair and 2/3 the Y pair, each pair spanning
    opposite corners. A tilt raises one arm of a pair by as much as it lowers
    the other, which is why the height offset is added and subtracted.
    """
    ik_height = height_m + HEIGHT_ORIGIN
    xh = height_difference_from_tilt(x_tilt_deg)
    yh = height_difference_from_tilt(y_tilt_deg)
    xw = width_difference_from_tilt(x_tilt_deg)
    yw = width_difference_from_tilt(y_tilt_deg)
    return [
        joint1_rotation(ik_height + xh, xw),
        joint1_rotation(ik_height - xh, xw),
        joint1_rotation(ik_height + yh, yw),
        joint1_rotation(ik_height - yh, yw),
    ]


def forward_height(theta1: float, offset_q: float = 0.0) -> float:
    """Joint height for a given arm angle — the inverse of joint1_rotation,
    used to check the IK against itself."""
    q = Q + offset_q
    inner = L2 * L2 - (q - L1 * math.cos(theta1)) ** 2
    if inner < 0.0:
        return float("nan")
    return L1 * math.sin(theta1) + math.sqrt(inner)


ORIGIN_ANGLES: List[float] = arm_angles(0.0, 0.0, 0.0)


def apply_trim(poses: Sequence[Tuple[float, float, float, float]],
               trim_x: float, trim_y: float) -> List[Tuple[float, float, float, float]]:
    """Add the mechanical levelling offset to every commanded tilt.

    The plate does not sit level when all four arms are at their origin — arm
    length tolerances and how the joints seated during assembly leave a small
    standing tilt. That offset is a property of the machine, not of any
    command, so it is added to everything: a "level" pose is whatever tilt
    actually makes the plate level, and the controller then works in a frame
    where zero really means zero.

    Deliberately NOT folded into ORIGIN_ANGLES. That constant is the firmware's
    power-on reference, which serialize() subtracts from every target; putting
    the trim there as well would cancel it out and the plate would never move.
    """
    return [(h, xt + trim_x, yt + trim_y, t) for h, xt, yt, t in poses]


# The three distinct ways four arms split into two pairs. Each tilt pair must
# span OPPOSITE corners of the plate; if the motors are connected so a pair
# spans adjacent corners, both tilt commands act on the same physical axis and
# the plate has only one usable tilt direction. Swapping the two members of a
# pair only flips that tilt's sign, which the axis mapping already handles, so
# these three are the whole space.
PAIRINGS = {
    "0+1 / 2+3": (0, 1, 2, 3),
    "0+2 / 1+3": (0, 2, 1, 3),
    "0+3 / 1+2": (0, 3, 1, 2),
}


def serialize(poses: Sequence[Tuple[float, float, float, float]],
              order: Optional[Sequence[int]] = None) -> str:
    """Build one wire line from a sequence of (height_m, x_tilt, y_tilt, move_time).

    Angles go out as a difference from the origin pose. The firmware validates
    each batch's marker and skips any batch whose marker does not match, so
    the numbering must start at 11 and step by 11.
    """
    parts: List[str] = []
    for batch, (height, xt, yt, move_time) in enumerate(poses, start=1):
        angles = arm_angles(height, xt, yt)
        diff = [angles[i] - ORIGIN_ANGLES[i] for i in range(4)]
        pairing = MOTOR_ORDER if order is None else order
        ordered = [diff[pairing[i]] for i in range(4)]
        parts.append("%.5f" % (11.0 * batch))
        parts.extend("%.5f" % a for a in ordered)
        parts.append("%.5f" % max(MOVE_DURATION_FLOOR, move_time))
    return ":".join(parts)


def pulses_for(angle_rad: float) -> int:
    """What the firmware will turn an angle into, for the diagnostics readout."""
    return int(PULSES_PER_REV * (angle_rad / (2.0 * math.pi)))
