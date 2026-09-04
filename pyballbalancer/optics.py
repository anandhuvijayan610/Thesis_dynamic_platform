"""What the camera can see of the plate, and what the throw actually does.

Two pieces of physics that decide whether a juggle works, kept together
because they pull against each other and the choice of stroke is the
compromise between them.

The camera sits close underneath the transparent plate looking up, so it does
not see the whole 299 mm plate at all -- it sees a narrow band, and that band
widens in proportion to how far the plate is from the lens. Raising the plate
therefore buys room for the ball to move before it vanishes, which is the
failure that looks like "the ball jumped off". It costs image scale in the
same proportion, so the ball gets smaller and every pixel is worth more
millimetres.

The throw pulls the other way. The arms run out of reach 97 mm above their
rest position and need steeply more pulses per millimetre as they approach it,
so a high stroke is a slow stroke, and a slow stroke does not throw.

Constants are from the rig's calibration (three commanded heights, five
samples each, least-squares fit; residuals under 0.6 mm). The one number worth
re-deriving if the camera is ever moved is CAMERA_TO_PLATE_AT_REST.
"""
from __future__ import annotations

import math

FOV_DEGREES = 60.41            # across the 640 px axis of the sensor
FRAME_W, FRAME_H = 640, 480    # as camera.py actually receives it, landscape
# NOTE: the Unity host ran this camera in its native 480x640 portrait mode.
# This app requests 640x480 through CAP_DSHOW and gets it, so the axes are
# the other way round here. DEG_PER_PX is unaffected - the pixels are square
# and the calibration fitted an angular scale, not a frame shape - but the
# window is not: getting this backwards names the wide axis as the limit
# when the short one is what actually loses the ball.
CAMERA_TO_PLATE_AT_REST = 67.95   # mm, plate at its mechanical dead position
BALL_RADIUS_MM = 20.0
G = 9.81

DEG_PER_PX = FOV_DEGREES / 640.0


def camera_distance(height_mm: float) -> float:
    """Lens to plate, for a plate that height above its rest position.

    Higher is FURTHER: the camera is below the plate. Getting this backwards
    is a mistake the rig has made before, and it hides well, because a sign
    error here cancels against a wrongly fitted offset at the one height the
    pair was fitted at.
    """
    return CAMERA_TO_PLATE_AT_REST + height_mm


def ball_radius_px(height_mm: float) -> float:
    """How large the ball looks resting on a plate at that height."""
    d = camera_distance(height_mm)
    return math.degrees(math.atan(BALL_RADIUS_MM / d)) / DEG_PER_PX


def px_per_mm(height_mm: float) -> float:
    d = camera_distance(height_mm)
    return 1.0 / (d * math.tan(math.radians(DEG_PER_PX)))


def half_window_mm(height_mm: float) -> tuple:
    """Half the visible patch of the plate, (across, down) the frame.

    This is the number that matters: a ball further than this from the centre
    is not on a plate the controller can see, whatever the plate is doing.
    """
    d = camera_distance(height_mm)
    return (d * math.tan(math.radians(FRAME_W / 2 * DEG_PER_PX)),
            d * math.tan(math.radians(FRAME_H / 2 * DEG_PER_PX)))


def tight_window_mm(height_mm: float) -> float:
    """The half-window on whichever axis runs out first.

    A ball does not care which way round the sensor is; it is lost as soon as
    it crosses the nearer edge. Quoting the wide axis flatters the machine by
    a third here, so anything reporting headroom should use this.
    """
    return min(half_window_mm(height_mm))


def throw(amplitude_mm: float, rise_s: float) -> dict:
    """Where a half-cosine stroke actually parts company with the ball.

    Not at the top of the stroke, and not at peak speed. The plate accelerates
    upward, then decelerates; the ball is released the instant that
    deceleration passes g, which is part way up and still climbing. Taking the
    peak velocity as the exit velocity therefore overstates the hop, and the
    error grows as the stroke gets gentler -- exactly where the answer matters,
    because that is where the throw is about to fail altogether.

    Returns None if the stroke never exceeds 1 g, which means the ball simply
    rides up and down in contact and never leaves.
    """
    a = amplitude_mm / 1000.0
    t = max(1e-6, rise_s)
    peak = math.pi ** 2 * a / (2.0 * t * t)
    if peak <= G:
        return None
    k = G / peak
    t_sep = t * math.acos(-k) / math.pi
    x_sep = a / 2.0 * (1.0 - math.cos(math.pi * t_sep / t))
    v_sep = math.pi * a / (2.0 * t) * math.sin(math.pi * t_sep / t)
    apex = x_sep + v_sep * v_sep / (2.0 * G)
    # Back down to the plate's top, not to where it left: the plate has kept
    # rising underneath it. Solving x_sep + v*tau - g*tau^2/2 = a for tau, the
    # constant term is (a - x_sep) -- the ball still has that far to climb --
    # and getting the sign the other way round inflates the flight by the whole
    # of the remaining stroke, which then sets a top dwell far too long.
    disc = v_sep * v_sep - 2.0 * G * (a - x_sep)
    if disc < 0.0:
        return None
    hang = (v_sep + math.sqrt(disc)) / G - (t - t_sep)
    return dict(peak_g=peak / G,
                exit_speed=v_sep,
                release_mm=x_sep * 1000.0,
                clearance_mm=(apex - a) * 1000.0,
                hang_time=hang)
