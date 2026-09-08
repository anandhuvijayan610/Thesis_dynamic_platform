"""Live-tunable parameter store.

Every knob the application exposes is declared once in SPECS. The GUI builds
its widgets from that declaration, so a parameter cannot exist in the control
maths without also appearing on screen — which is the whole point of replacing
the Unity front end.

Reads happen on the camera and control threads, writes on the GUI thread, so
the backing dict is guarded by a lock. Values are plain Python scalars, and a
reader takes a snapshot rather than holding the lock across its own work.
"""
from __future__ import annotations

import json
import threading
from typing import Any, Dict, List, NamedTuple

from PyQt5.QtCore import QObject, pyqtSignal


class Spec(NamedTuple):
    """Declaration of one tunable parameter."""
    key: str
    label: str
    group: str          # which GUI tab it belongs to
    kind: str           # "float" | "int" | "bool" | "choice"
    default: Any
    lo: float = 0.0
    hi: float = 1.0
    step: float = 0.01
    choices: tuple = ()
    tip: str = ""


# --------------------------------------------------------------------------
# Camera. These are pushed into cv2.VideoCapture, which on Windows accepts
# them only through the DirectShow backend; several are ignored by MSMF.
# --------------------------------------------------------------------------
SPECS: List[Spec] = [
    Spec("cam_index", "Device index", "Camera", "int", 0, 0, 8, 1),
    Spec("cam_width", "Width", "Camera", "int", 640, 160, 1920, 16),
    Spec("cam_height", "Height", "Camera", "int", 480, 120, 1080, 16),
    Spec("cam_fps", "Requested FPS", "Camera", "int", 120, 5, 260, 5,
         tip="The driver may negotiate something lower; the measured rate is on the plot."),
    Spec("cam_auto_exposure", "Auto exposure", "Camera", "bool", False),
    Spec("cam_exposure", "Exposure", "Camera", "float", -8, -13, 0, 1,
         tip="Log2 seconds on most UVC cameras, and the single most important "
             "setting for detection. Too bright does not wash the ball out of "
             "the picture, which would at least be obvious - it makes the ball "
             "measure SMALL while still detecting on every frame. Clipped "
             "pixels lose their saturation, drop out of the colour gate, and "
             "eat the mask inward from the brightest part of the ball.\n\n"
             "That is why detection rate is a useless health check on its own. "
             "Measured at the working origin against a predicted 152.5 px, "
             "60 frames per setting, twice: -8 reads 150.8 px with no clipping "
             "at all, -7 reads 145.6 at 8% clipped, -6 reads 134.9 at 70%, and "
             "-5 reads 110.5 at 98%. Every one of those found the ball in 57 "
             "of 60 frames. The Session tab now prints measured against "
             "expected radius, which is the check that actually catches this.\n\n"
             "Nothing below -9 detects at all, so the usable window is narrow. "
             "Re-run exposuretest.py after any change to the lighting - the "
             "room light here moves enough between sessions to shift the whole "
             "table by a stop."),
    Spec("cam_gain", "Gain", "Camera", "int", 120, 0, 255, 1,
         tip="Paired with the exposure above: together they decide whether the "
             "ball keeps its colour or blows out to white. 120 is measured, not "
             "reasoned - and it is NOT monotonic on this camera, which is worth "
             "knowing before trusting a hill-climb. At exposure -8 the clipped "
             "fraction goes 5% at gain 60, 0% at 120, then 42% at 200, and both "
             "sweeps put the minimum at 120. These DSHOW controls interact in "
             "ways the driver does not document and the readback does not show "
             "- it echoes whatever was requested regardless. Judge by the "
             "measured radius, never by the readback."),
    Spec("cam_brightness", "Brightness", "Camera", "int", 0, -64, 64, 1),
    Spec("cam_saturation", "Saturation", "Camera", "int", 160, 0, 255, 1),
    Spec("cam_contrast", "Contrast", "Camera", "int", 25, 0, 255, 1),

    # ----------------------------------------------------------------------
    # Vision
    # ----------------------------------------------------------------------
    Spec("vis_strategy", "Strategy", "Vision", "choice", "Threshold + contour",
         choices=("Threshold + contour", "HoughCircles")),
    Spec("vis_use_hsv", "Gate on HSV", "Vision", "bool", True,
         tip="Off falls back to the red-minus-blue difference, which suits a warm ball on a neutral plate."),
    Spec("vis_h_lo", "Hue low", "Vision", "int", 0, 0, 179, 1),
    Spec("vis_h_hi", "Hue high", "Vision", "int", 20, 0, 179, 1,
         tip="At the shipped exposure the ball is a deep, fully saturated red: "
             "95% of its pixels sit at hue 0-4, so this has plenty of margin. "
             "It only needed widening when the ball was overexposed, and the "
             "cure for that is the exposure, not the hue."),
    Spec("vis_s_lo", "Sat low", "Vision", "int", 150, 0, 255, 1,
         tip="Saturation is what separates ball from background here, and it "
             "does so cleanly: measured, 95% of the ball sits at S=255 while "
             "the ceiling is grey. Value cannot do it - the background reaches "
             "V=110 and the ball starts at V=101 - so this is the gate that "
             "matters. It can be this strict only because the ball is not "
             "overexposed; a blown-out highlight has no saturation at all."),
    Spec("vis_s_hi", "Sat high", "Vision", "int", 255, 0, 255, 1),
    Spec("vis_v_lo", "Val low", "Vision", "int", 15, 0, 255, 1,
         tip="Deliberately loose, and 15 rather than the 50 it used to be. "
             "Saturation is what separates ball from background here, so value "
             "only has to reject sensor noise in the black background - and at "
             "50 it was doing far more than that.\n\n"
             "Measured when the ball came out as a crescent: 95% of its pixels "
             "passed the saturation floor but only 54% passed V>=50, because "
             "the ball's own value runs median 53, p25 17, p5 2. Nearly half of "
             "it was being cut off, giving fill 0.76 and circularity 0.31 - "
             "rejected as not round, when nothing was wrong with the ball. At "
             "15 the whole ball comes back: fill 0.984, circularity 0.883.\n\n"
             "Do not go much lower. At 8 the background starts clearing the "
             "floor too and the mask breaks into 2-3 blobs; 15 holds at one."),
    Spec("vis_v_hi", "Val high", "Vision", "int", 255, 0, 255, 1),
    Spec("vis_diff_thresh", "r−b threshold", "Vision", "int", 70, 0, 255, 1),
    Spec("vis_kernel", "Morphology kernel", "Vision", "int", 7, 0, 15, 1,
         tip="Radius of the ellipse used to open then close the mask. Raised "
             "from 3 to 7 alongside the value floor: a lower floor lets in more "
             "speckle, and the larger kernel is what keeps the ball a single "
             "blob rather than several. Measured at the shipped floor of 15, "
             "averaged over 15 frames: kernel 3 gives 4.1 blobs, 5 gives 1.8, "
             "7 gives 1.1 - and circularity improves with it too, 0.871 to "
             "0.883, because the boundary comes out smoother."),
    Spec("vis_min_area", "Min blob area", "Vision", "int", 120, 1, 200000, 10),
    Spec("vis_max_area", "Max blob area", "Vision", "int", 120000, 1, 500000, 100),
    Spec("vis_min_fill", "Min fill", "Vision", "float", 0.80, 0.0, 1.0, 0.01,
         tip="The roundness gate that actually decides. Fill is the blob's "
             "area-equivalent radius over its minimum enclosing circle, so it "
             "measures how well the shape packs a disc WITHOUT looking at the "
             "boundary - which is the whole point, because the boundary is the "
             "noisy part. Measured here: real ball 0.99, the same ball with a "
             "serrated shaded limb still 0.93, a 2:1 bar 0.72, a 4:1 bar 0.55, "
             "a 10:1 bar 0.36. 0.80 separates the ball from all of them with "
             "room to spare, and does it whether or not the edge is clean."),
    Spec("vis_min_circularity", "Min circularity", "Vision", "float", 0.30, 0.0, 1.0, 0.01,
         tip="4*pi*A/P^2, a loose backstop only - fill above is the gate that "
             "decides. This was 0.55 and it FALSELY REJECTED THE BALL: the "
             "perimeter term makes it collapse on a ragged edge even when the "
             "shape is a perfect disc. When the ball's shaded limb sits near "
             "the brightness floor its outline serrates, and the same ball "
             "that scores 0.88 in even light scores 0.43 - below 0.55, so the "
             "detector reported no ball at all while showing a clean round "
             "blob on screen. Fill stayed at 0.93 throughout. Kept low enough "
             "to still catch genuinely stringy shapes (a 10:1 bar scores "
             "0.26) without ever being the reason a real ball is turned down."),
    Spec("vis_hough_dp", "Hough dp", "Vision", "float", 1.0, 1.0, 4.0, 0.1),
    Spec("vis_hough_mindist", "Hough min dist", "Vision", "int", 120, 5, 600, 5),
    Spec("vis_hough_p1", "Hough param1", "Vision", "int", 150, 10, 400, 5,
         tip="Canny high threshold. Has little effect here because the input is already binary."),
    Spec("vis_hough_p2", "Hough param2", "Vision", "int", 16, 5, 200, 1,
         tip="Accumulator votes needed to accept a circle. Kept low because the transform "
             "runs on the binary mask, whose thinned edges vote far less than a grey image's "
             "would: measured on synthetic balls of radius 10-160 px, 32 finds nothing at all "
             "while 16 finds every one with no false positives."),
    Spec("vis_min_radius", "Min radius px", "Vision", "int", 8, 1, 400, 1),
    Spec("vis_max_radius", "Max radius px", "Vision", "int", 200, 2, 800, 1),
    Spec("vis_show_mask", "Show mask", "Vision", "bool", False),

    # ----------------------------------------------------------------------
    # Which candidate is the ball. A single frame cannot answer that: a
    # partly-masked ball breaks into several contours, and background clutter
    # can be rounder than the ball itself. Continuity between frames can.
    # ----------------------------------------------------------------------
    Spec("vis_roi_radius", "Plate radius (px)", "Vision", "int", 400, 10, 640, 5,
         tip="Candidates further than this from frame centre are discarded. It "
             "used to be the tightest limit in the system, at 260, which was "
             "right while a ball touching the frame edge was unusable. Now that "
             "a clipped ball has its centre reconstructed from its arc, its "
             "centre legitimately reads up to about 370 px out, and a 260 px "
             "limit would throw away exactly the readings that were the point. "
             "400 is the frame corner, so this no longer rejects anything on "
             "its own - the arc tolerance and radius continuity do that work."),
    Spec("vis_edge_margin", "Frame edge margin (px)", "Vision", "int", 3, 0, 100, 1,
         tip="Boundary points this close to the frame edge trace the picture, "
             "not the ball, so they are left out of the arc fit. Only that: a "
             "clipped ball is no longer rejected, it is reconstructed."),
    Spec("vis_min_arc_points", "Arc points needed", "Vision", "int",
         40, 8, 400, 5,
         tip="How much of the ball's outline must still be inside the frame "
             "before its centre is worth reconstructing. Measured on this rig, "
             "the fit holds to 2.5 px with 73% of the ball outside (177 points) "
             "and degrades to 4.5 px at 89% (113 points)."),
    Spec("vis_max_arc_residual", "Arc fit tolerance (px)", "Vision", "float",
         4.0, 0.5, 40.0, 0.5,
         tip="How well the visible outline must actually lie on a circle. This "
             "replaces the circularity test for a clipped ball, which can never "
             "pass one: a partly-visible ball is not round, but its edge is "
             "still a true arc. A straight mask edge or two merged blobs are "
             "not, and fail here."),
    Spec("vis_lock_frames", "Frames to trust a ball", "Vision", "int", 4, 1, 30, 1,
         tip="A new candidate must hold still for this many frames before it "
             "is believed. Without it a cold start can latch onto the ceiling, "
             "and the proximity gate then defends that mistake forever. Set 1 "
             "to disable the wait."),
    Spec("vis_lock_tol_px", "Hold-still tolerance (px)", "Vision", "int",
         30, 2, 300, 5,
         tip="How far a candidate may move between frames and still count as "
             "the same one while earning trust."),
    Spec("vis_radius_tolerance", "Radius continuity", "Vision", "float",
         0.70, 0.1, 1.0, 0.05,
         tip="Once tracking, a candidate whose radius is less than this "
             "fraction of the tracked one (or more than its reciprocal) is "
             "ignored. A ball's size changes only slowly, with height, so a "
             "sudden drop means the blob is a fragment - clipped by the frame "
             "edge, or split by the logo printed on the ball. A fragment "
             "reports a biased centre AND a smaller radius, so it slips past "
             "any guard that trusts the radius it claims. 1.0 disables it."),
    Spec("vis_gate_px", "Tracking gate (px)", "Vision", "int", 150, 10, 640, 10,
         tip="Once tracking, only candidates this close to the last accepted "
             "position are considered. Bounds how far a ball can appear to "
             "jump in one frame."),
    Spec("vis_gate_frames", "Frames before giving up", "Vision", "int",
         30, 1, 300, 1,
         tip="Consecutive misses before the lock is dropped and the search "
             "starts over, so a ball that is picked up and replaced is found "
             "again rather than tracked to where it used to be."),

    # ----------------------------------------------------------------------
    # Control
    # ----------------------------------------------------------------------
    Spec("ctl_mode", "Mode", "Control", "choice", "PID",
         choices=("PID", "Analytical (mirror)")),
    Spec("ctl_rate_hz", "Command rate (Hz)", "Control", "int", 100, 5, 250, 5),
    Spec("ctl_vel_window", "Velocity window (samples)", "Control", "int", 6, 2, 60, 1,
         tip="Least-squares fit over this many recent samples. Longer is "
             "smoother but adds lag. The derivative term multiplies this "
             "estimate, so a short window turns position noise into tilt "
             "jitter: at 6 samples the residual orbit measured 24 mm against "
             "20 mm at 12."),
    Spec("ctl_target_x", "Target X (px from centre)", "Control", "float", 0.0, -640, 640, 1),
    Spec("ctl_target_y", "Target Y (px from centre)", "Control", "float", 0.0, -640, 640, 1),
    Spec("ctl_max_tilt", "Max tilt (deg)", "Control", "float", 3.0, 0.1, 20.0, 0.1,
         tip="Hard clamp applied to every command, whatever the controller asks "
             "for. This bounds how far the plate leans, not how fast."),
    Spec("ctl_slew_rate", "Max tilt rate (deg/s)", "Control", "float",
         25.0, 0.0, 120.0, 1.0,
         tip="Bounds how fast the command may change, which is the part the "
             "ball feels. Judge it by the acceleration where the BALL is, not "
             "at the rim: tilting pivots the plate about its middle, so a ball "
             "60 mm out feels about 40% of the rim figure, and sizing this "
             "from the rim is roughly three times too strict. At 25 deg/s with "
             "a 0.10 s move that is 0.13 g at the ball and 0.33 g at the rim, "
             "both under the 1 g that lifts it off. Do not go far lower: "
             "20 deg/s fails to settle with 1.5 mm of noise, 12 fails "
             "outright. 0 disables the limit."),

    Spec("pid_kp_x", "Kp X", "Control", "float", 0.020, 0.0, 1.0, 0.001,
         tip="Lowered from 0.05 once the camera was measured at 30 fps rather "
             "than the 100 assumed. At 30 Hz the loop carries far more lag than "
             "the old gains were derived against, and they oscillated: "
             "simulated at the real rate they leave a 30 mm swing where 0.020 "
             "leaves 5."),
    Spec("pid_ki_x", "Ki X", "Control", "float", 0.100, 0.0, 1.0, 0.001,
         tip="Removes the standing offset a sloped plate leaves behind. The "
             "plate is levelled at the origin but balancing runs 40 mm up, "
             "where it need not be level; a proportional loop then parks the "
             "ball off-centre by however much tilt the slope needs. Simulated "
             "against a 1.4 deg slope: ki=0 leaves 28 mm of offset, ki=0.1 "
             "leaves 0 and halves the peak excursion. ki=0.8 goes unstable."),
    Spec("pid_kd_x", "Kd X", "Control", "float", 0.040, 0.0, 1.0, 0.001,
         tip="The derivative acts on a velocity estimated from camera samples, "
             "so at 30 fps it is inherently late; too much of it then drives "
             "the oscillation it is meant to damp."),
    Spec("pid_kp_y", "Kp Y", "Control", "float", 0.020, 0.0, 1.0, 0.001,
         tip="Lowered from 0.05 once the camera was measured at 30 fps rather "
             "than the 100 assumed. At 30 Hz the loop carries far more lag than "
             "the old gains were derived against, and they oscillated: "
             "simulated at the real rate they leave a 30 mm swing where 0.020 "
             "leaves 5."),
    Spec("pid_ki_y", "Ki Y", "Control", "float", 0.100, 0.0, 1.0, 0.001,
         tip="Removes the standing offset a sloped plate leaves behind. The "
             "plate is levelled at the origin but balancing runs 40 mm up, "
             "where it need not be level; a proportional loop then parks the "
             "ball off-centre by however much tilt the slope needs. Simulated "
             "against a 1.4 deg slope: ki=0 leaves 28 mm of offset, ki=0.1 "
             "leaves 0 and halves the peak excursion. ki=0.8 goes unstable."),
    Spec("pid_kd_y", "Kd Y", "Control", "float", 0.040, 0.0, 1.0, 0.001,
         tip="The derivative acts on a velocity estimated from camera samples, "
             "so at 30 fps it is inherently late; too much of it then drives "
             "the oscillation it is meant to damp."),
    Spec("pid_i_clamp", "Integral clamp", "Control", "float", 20.0, 0.0, 50.0, 0.1,
         tip="Bounds the integral, and with it the tilt the integral can ask "
             "for: at most Ki x this. It was 2.0, which capped that at 0.2 deg "
             "with Ki=0.1 - far short of the ~1.4 deg a real plate slope needs, "
             "so the offset stayed however large Ki was made. This is also the "
             "only anti-windup in the loop, which is why it is not larger."),

    Spec("ana_restitution", "Restitution e", "Control", "float", 0.75, 0.05, 1.0, 0.01),
    Spec("ana_flight_time", "Flight time (s)", "Control", "float", 0.35, 0.05, 2.0, 0.01,
         tip="Time allowed to reach the target. Shorter asks for a more aggressive tilt."),
    Spec("ana_gain", "Output gain", "Control", "float", 1.0, 0.0, 5.0, 0.05),

    Spec("ctl_recover_seconds", "Recover for (s)", "Control", "float",
         1.5, 0.0, 10.0, 0.1,
         tip="How long to keep leaning toward a ball that has gone out of "
             "sight before giving up and levelling. The camera sees a band far "
             "narrower than the plate - about +-28 mm against +-150 - so a "
             "ball can be on the plate and simply invisible. Levelling then is "
             "the worst response: on any residual slope it lets the ball keep "
             "going, turning a momentary loss into a permanent one. 0 restores "
             "the old behaviour of levelling immediately."),
    Spec("ctl_recover_tilt", "Recover tilt (deg)", "Control", "float",
         2.5, 0.0, 8.0, 0.1,
         tip="How hard to lean while trying to bring an unseen ball back. "
             "Simulated against a ball leaving the visible band: 1.5 deg "
             "recovers one drifting at 40 mm/s, 2.5 recovers 100, and 3.0 is "
             "WORSE again at 60 - it hauls the ball back so hard that it "
             "leaves the far side. More is not better here."),
    Spec("ctl_scale_by_radius", "Scale gains with height", "Control", "bool", True,
         tip="The gains are in degrees per PIXEL, but the ball is steered in "
             "millimetres, and the two are only the same thing at one plate "
             "height. The camera sits below the plate, so raising the plate "
             "moves it away and every millimetre of ball travel becomes fewer "
             "pixels: at the 40 mm balancing plate the ball spans 111 px, at "
             "the 70 mm juggling catch only 87, so the same gains push 21% "
             "less hard exactly when the ball is moving fastest. The ball's "
             "own apparent radius measures that distance directly - a 40 mm "
             "ball covering 2r pixels IS the scale - so the loop can correct "
             "for it with no calibration constant, no FOV and no dependence "
             "on the plate arriving where it was told."),
    Spec("ctl_ref_radius", "Radius gains were tuned at (px)", "Control", "float",
         111.0, 20.0, 300.0, 1.0,
         tip="The apparent radius at which the gains mean what they say; the "
             "output is multiplied by this over the measured radius. 111 px "
             "is the ball resting on the plate at the balancing height, which "
             "is where the tuning was done, so balancing is unchanged and only "
             "the higher juggling stroke is affected. To re-measure it, sit "
             "the ball on the plate in balancing mode and read the radius off "
             "the Session tab."),
    Spec("ctl_invert_x", "Invert X", "Control", "bool", False),
    Spec("ctl_invert_y", "Invert Y", "Control", "bool", False),
    Spec("ctl_swap_axes", "Swap axes", "Control", "bool", False,
         tip="Set these three so a ball rolling right makes the plate lift the right-hand side."),

    # ----------------------------------------------------------------------
    # Serial
    # ----------------------------------------------------------------------
    Spec("ser_port", "Port", "Serial", "choice", "", choices=()),
    Spec("ser_baud", "Baud", "Serial", "choice", 921600,
         choices=(9600, 19200, 57600, 115200, 250000, 460800, 921600),
         tip="The Teensy ignores this — USB CDC always runs at full speed — so "
             "a mismatch here cannot be what stops the plate moving."),
    Spec("ser_autoconnect", "Connect on start", "Serial", "bool", True,
         tip="Opens the port as soon as the window appears. Opening it commands "
             "no motion, and it removes the step whose omission makes every "
             "button on the Machine tab look dead."),

    # ----------------------------------------------------------------------
    # Machine. Heights are mm above the plate's rest position; the firmware
    # works in arm angles and knows nothing about any of this.
    # ----------------------------------------------------------------------
    Spec("mac_origin_offset", "Working origin (mm)", "Machine", "float", 20.0, 0.0, 60.0, 1.0,
         tip="Added to every commanded height, so every mode rides on it: the "
             "balancing and juggling heights are offsets from here, not "
             "absolutes. The plate at rest has no downward travel, so the "
             "working origin is parked this far above it.\n\n"
             "IT IS MEASURED FROM THE FIRMWARE'S ZERO, WHICH IS ITS POWER-ON "
             "POSITION - not from true mechanical dead. The two are the same "
             "only if the board was powered up with the plate actually at "
             "rest, and they drift apart after skipped steps or a power-up "
             "with the plate held. When that happens the plate sits lower than "
             "this number claims and the linkage starts to foul; raised 10 to "
             "20 mm on 2026-09-02 for exactly that. If it fouls again, "
             "power-cycle with the plate at rest before adding more here - "
             "otherwise this number quietly becomes the tally of every step "
             "ever lost.\n\n"
             "Raising it costs nothing optically and helps: the camera looks "
             "up from below, so a higher plate is further away and the visible "
             "band widens. 10 -> 20 mm took the window at the origin from "
             "+-32.5 to +-36.7 mm. What it does cost is the trim, which is per "
             "height - re-level after changing this."),
    # Settled on the machine 2026-09-02, with arm pairing 0+2 / 1+3, by
    # adjusting until the ball sits still in the middle of the plate and does
    # not roll. That is the definition that matters: not what a spirit level
    # says at the origin, but where the ball stays at the height balancing
    # actually runs.
    #
    # The trim is PER PAIRING -- changing which motor each tilt drives
    # invalidates it -- and this pair differs from the origin-levelled values
    # by about 1.5 deg, which is the residual slope the linkage carries between
    # the origin and 40 mm. Attempts to measure that slope from the ball's
    # drift open-loop were not reproducible (the same trim read +334,+748 one
    # run and -677,-710 the next), so it was found by adjustment instead.
    #
    # Nothing persists between runs: every script builds a fresh store from
    # these defaults, so anything dialled in through the GUI alone is lost when
    # it closes. Values worth keeping belong here.
    Spec("mac_motor_order", "Arm pairing", "Machine", "choice", "0+2 / 1+3",
         choices=("0+1 / 2+3", "0+2 / 1+3", "0+3 / 1+2"),
         tip="Which computed arm drives which motor. Each tilt pair must span "
             "OPPOSITE corners of the plate. If a pair spans adjacent corners "
             "instead, both tilt commands act on the same physical axis, the "
             "plate can only push the ball along one line, and no controller "
             "can hold it in two dimensions. Check it by eye: press X+ on this "
             "tab and watch which corners rise - they must be diagonal to each "
             "other, not side by side."),
    Spec("mac_trim_x", "Level trim X (deg)", "Machine", "float", -0.40, -8.0, 8.0, 0.05,
         tip="Standing tilt of the plate when all four arms are at their "
             "origin, cancelled out. Added to every commanded tilt, so a "
             "'level' command becomes whatever actually makes the plate level "
             "and the controller works in a frame where zero means zero.\n\n"
             "Set by hand with the nudge buttons below and a spirit level, and "
             "it is NOT a constant of the machine - it has been -0.20, then "
             "-1.30, -1.40, now -2.50 - and it jumped a full degree purely from "
             "moving the working origin 10 mm, which is the clearest evidence "
             "that it is a property of the height, not of the machine. "
             "Re-check it whenever the arms are disturbed, "
             "and in particular after the plate has been left holding a pose "
             "or after a hard juggle. The way to tell it has drifted is a ball "
             "that will not settle in the middle no matter how the gains are "
             "tuned; 0.6 deg of residual tilt accelerates the ball at about "
             "70 mm/s^2, which no gain change removes."),
    Spec("mac_trim_y", "Level trim Y (deg)", "Machine", "float", -0.40, -8.0, 8.0, 0.05,
         tip="The same for the other axis; it has been +1.50, +0.35, -0.70 and "
             "now -2.10 on this rig, so do not treat any of those as a target to "
             "return to - measure it. Trim X first: a tilt on one pair changes "
             "how level the other pair looks, so the second axis has to be set "
             "after the first, not alongside it."),
    Spec("mac_trim_step", "Trim nudge (deg)", "Machine", "float", 0.10, 0.01, 1.0, 0.01,
         tip="How much each nudge button moves the trim."),

    Spec("mac_move_time", "Move time (s)", "Machine", "float", 0.50, 0.05, 3.0, 0.05,
         tip="Used by the test buttons. The firmware clamps anything under 0.05 s up to it."),
    Spec("mac_test_height", "Test height (mm)", "Machine", "float", 20.0, 0.0, 70.0, 1.0),
    Spec("mac_test_tilt", "Test tilt (deg)", "Machine", "float", 2.0, 0.1, 8.0, 0.1),
    Spec("mac_osc_low", "Oscillate low (mm)", "Machine", "float", 10.0, 0.0, 70.0, 1.0),
    Spec("mac_osc_high", "Oscillate high (mm)", "Machine", "float", 30.0, 0.0, 70.0, 1.0),
    Spec("mac_osc_time", "Oscillate stroke (s)", "Machine", "float", 0.40, 0.05, 3.0, 0.05),
    Spec("mac_osc_cycles", "Oscillate cycles", "Machine", "int", 4, 1, 40, 1,
         tip="Sent as one multi-batch line; the firmware executes them back to back."),

    # ----------------------------------------------------------------------
    # Modes. Heights are mm above the working origin, so they shift with it.
    # ----------------------------------------------------------------------
    Spec("mod_mode", "Mode", "Modes", "choice", "Juggling",
         choices=("Balancing", "Balance then rest", "Balance and juggle",
                  "Juggling"),
         tip="Started and stopped from the Session tab. 'Balance then rest' "
             "holds the ball a while then softens the gains so it stops in the "
             "middle. 'Balance and juggle' holds it centred and throws a small "
             "hop every few seconds. 'Juggling' bounces continuously."),
    Spec("mod_balance_height", "Balancing height (mm)", "Modes", "float",
         30.0, 0.0, 70.0, 1.0,
         tip="The plate rises to this and holds it while the controller tilts. "
             "Lowered from 40 to make room for a bigger hop: the arms reach "
             "97 mm above rest, but near the top each mm of plate costs far "
             "more arm rotation, so a large fast move there exceeds the "
             "firmware's 25000 steps/s. Starting lower makes the same hop "
             "cheaper in steps. The cost is camera reach - the ball is nearer "
             "the lens, so its usable travel falls from about +-27 mm to +-23. "
             "NOTE the levelling trim is per height; re-check it after moving "
             "this."),
    Spec("mod_rise_time", "Rise time (s)", "Modes", "float", 0.80, 0.15, 3.0, 0.05,
         tip="How long the initial climb takes. Sent once, not repeated: a "
             "half-cosine move restarted every tick never leaves the ground. "
             "Fast rises throw the ball off - 40 mm in 0.25 s is already 1.3 g."),
    Spec("mod_settle_time", "Settle before tilting (s)", "Modes", "float",
         0.50, 0.0, 3.0, 0.05,
         tip="Quiet time after the climb before any tilt is applied, so the "
             "controller is not fighting a plate that is still moving."),
    Spec("mod_balance_move_time", "Balancing move time (s)", "Modes", "float",
         0.06, 0.05, 0.50, 0.01,
         tip="One tilt command per this interval, and with the firmware's "
             "0.05 s margin it IS the loop's transport delay. 0.10 was tried "
             "and preferred on the bench once, but that was before the camera "
             "was measured at 30 fps: at the real rate every setting that "
             "settles uses 0.06, and 0.10 leaves a 30 mm swing against 5. "
             "Delay, not gain, is what decides whether the ball circles."),

    # --- Balance and juggle ------------------------------------------------
    Spec("mod_hop_every", "Hop every (s)", "Modes", "float", 3.0, 0.5, 30.0, 0.5,
         tip="Time spent balancing between hops. The ball is held in the middle "
             "for this long, then thrown once, so it lands near where it left."),
    Spec("mod_hop_mm", "Hop rise (mm)", "Modes", "float", 50.0, 5.0, 60.0, 1.0,
         tip="How far the plate lifts to throw the ball. If the ball does not "
             "leave the plate, go BIGGER, not faster: 20 mm in 0.08 s is a "
             "higher peak g than 30 mm in 0.10 s and lifts nothing, because the "
             "shorter stroke gives the motors too little time to reach the "
             "speed asked for. Two ceilings bound this. The arms cannot reach "
             "beyond about 90 mm absolute, so balance height plus hop must stay "
             "under it - past that the kinematics silently clamp and the plate "
             "just does not go. And a big fast stroke can exceed the firmware's "
             "25000 steps/s: 50 mm in 0.12 s needs 28000 and would drop steps."),
    Spec("mod_hop_rise", "Hop rise time (s)", "Modes", "float",
         0.11, 0.05, 0.40, 0.01,
         tip="The throwing stroke. At 50 mm this is 2.1 g and the ball leaves "
             "at 0.71 m/s for a 26 mm hop with 0.15 s of air. Slower than it "
             "could be on purpose: a shorter stroke reaches a higher commanded "
             "g but the motors under-deliver it, which is why 20 mm in 0.08 s "
             "lifts nothing while 30 mm in 0.10 s does."),
    Spec("mod_hop_hang", "Hold at the top (s)", "Modes", "float",
         0.15, 0.02, 0.60, 0.01,
         tip="The plate waits here while the ball is in the air, so it is "
             "stationary when the ball comes back down rather than still "
             "moving. Match it to the airborne time above."),
    Spec("mod_hop_fall", "Return time (s)", "Modes", "float",
         0.25, 0.05, 1.00, 0.01,
         tip="Coming back down to the balancing height. Deliberately slower "
             "than the rise: the fall throws nothing, so speed here is only "
             "shaking the frame."),

    # --- Balance then rest -------------------------------------------------
    Spec("mod_hold_seconds", "Hold before resting (s)", "Modes", "float",
         10.0, 0.0, 300.0, 1.0,
         tip="How long to keep the lively behaviour before letting the ball "
             "come to a stop."),
    Spec("mod_rest_blend", "Blend into rest (s)", "Modes", "float",
         3.0, 0.1, 20.0, 0.5,
         tip="The gains cross over from the running set to the resting one "
             "across this. Simulated, an instant swap settles marginally "
             "faster, but a blend is what makes the ball visibly slow down "
             "rather than stop being chased."),
    Spec("mod_rest_kp", "Rest Kp", "Modes", "float", 0.020, 0.0, 1.0, 0.001,
         tip="Proportional gain once resting. Softer than the running value: "
             "the orbit is a limit cycle the loop delay sustains, and a gentler "
             "loop simply does not sustain it. Simulated at the shipped 0.15 s "
             "delay, residual swing falls from 28 mm to about 3."),
    Spec("mod_rest_kd", "Rest Kd", "Modes", "float", 0.030, 0.0, 1.0, 0.001),
    Spec("mod_rest_ki", "Rest Ki", "Modes", "float", 0.100, 0.0, 1.0, 0.001,
         tip="Kept at the running value: the integral is what holds the ball "
             "against the plate's residual slope, and dropping it here would "
             "let the resting position drift off centre."),
    Spec("mod_rest_window", "Rest velocity window", "Modes", "int", 8, 2, 60, 1,
         tip="A little longer than the running window, for less tilt jitter "
             "when the ball is nearly still. Counted in SAMPLES, and the camera "
             "delivers 30 a second, so this is 0.27 s of lag - it was 16, which "
             "is 0.53 s, and that alone left a 57 mm swing. Read every window "
             "in this application as samples divided by 30."),

    Spec("mod_jug_centre_px", "Centred within (px)", "Modes", "float",
         40.0, 5.0, 400.0, 5.0,
         tip="How close to the target the ball must be before juggling starts. "
             "Bouncing a ball that is not centred does not centre it - it loses "
             "it. Watching a run back: the ball began 250 px off centre, the "
             "plate threw it anyway, and nine cycles later it had walked out of "
             "the camera window. 40 px is about 7 mm at the juggling base."),
    Spec("mod_jug_centre_speed", "Centred below (px/s)", "Modes", "float",
         120.0, 10.0, 1000.0, 10.0,
         tip="And how slow. Position alone is not enough - a ball crossing the "
             "middle at speed is momentarily 'centred' and is the worst moment "
             "to throw it."),
    Spec("mod_jug_centre_hold", "Centred for (commands)", "Modes", "int",
         8, 1, 100, 1,
         tip="Consecutive checks that must pass before the oscillation begins, "
             "so a single lucky frame cannot start it. At the balancing move "
             "time this is roughly half a second of genuinely settled ball."),
    Spec("mod_jug_low", "Juggle low (mm)", "Modes", "float", 35.0, 0.0, 70.0, 1.0,
         tip="Bottom of the stroke, and the tightest the camera's view of the "
             "plate ever gets during a cycle. The camera is close underneath, "
             "so it sees a band far narrower than the plate and that band "
             "widens as the plate rises: +-37 mm across at a 30 mm plate, "
             "+-47 mm at 45 mm, +-53 mm at 60 mm. Raising the whole stroke is "
             "therefore the cheapest way to stop losing the ball. It is not "
             "free - the arm needs more pulses per millimetre above 70 mm, so "
             "a high base forces a slower, weaker throw."),
    Spec("mod_jug_high", "Juggle high (mm)", "Modes", "float", 51.0, 0.0, 87.0, 1.0,
         tip="Top of the stroke, and where the ball is caught. The arm runs "
             "out of reach 97 mm above its rest position and the pulses per "
             "millimetre climb steeply near it, so 87 mm is the ceiling here. "
             "A 16 mm stroke is deliberately short. Exit speed is capped by "
             "the firmware's step rate however far the plate travels, so a "
             "longer stroke buys no height and only costs time and reach - and "
             "height is not actually wanted. THIS IS THE KNOB FOR HOW HIGH THE "
             "BALL HOPS: 16 mm gives 6 mm of clearance, 20 mm gives 11 mm, "
             "25 mm gives 20 mm and is more than the loop can catch.\n\n"
             "A longer stroke paired with a longer rise would throw the same "
             "height more gently - 30 mm over 0.08 s gives the same 6 mm hop "
             "at 2.4 g instead of 3.2 g, since peak acceleration at fixed exit "
             "speed is pi*v/T. That was tried and reverted at the user's "
             "request; the numbers are here in case it is worth revisiting."),
    Spec("mod_jug_rise_time", "Juggle rise (s)", "Modes", "float",
         0.05, 0.05, 0.60, 0.01,
         tip="The stroke that throws the ball, at the firmware's 0.05 s floor. "
             "With the 16 mm stroke it gives 3.2 g and the ball separates "
             "carrying 0.48 m/s, for a hop 6 mm clear of the plate. Kept at "
             "the floor deliberately even though the throw is gentle: a short, "
             "sharp stroke and a long, soft one of the same exit speed differ "
             "in PEAK ACCELERATION, and that is the margin that decides "
             "whether the ball separates at all when the motors under-deliver. "
             "Shorten the stroke to throw less, not this."),
    Spec("mod_jug_top_dwell", "Top dwell (s)", "Modes", "float",
         0.07, 0.05, 1.00, 0.01,
         tip="Held still while the ball is airborne, so it lands on a "
             "stationary plate rather than one that is already dropping away. "
             "Matched to the flight: the ball is released 10 mm up the stroke "
             "and needs 0.064 s to come back down to the plate's top, which is "
             "LESS than the naive figure because the plate keeps climbing the "
             "remaining 10 mm to meet it. Too long is not harmless either - "
             "tilt cannot steer a ball that is in the air, so every extra "
             "hundredth is control authority thrown away."),
    Spec("mod_jug_fall_time", "Juggle fall (s)", "Modes", "float",
         0.16, 0.05, 1.50, 0.01,
         tip="Deliberately slower than the rise. The fall launches nothing, so "
             "speed here is structural excitation for no benefit - 7500 "
             "steps/s against the rise's 24000."),
    Spec("mod_jug_bottom_dwell", "Bottom dwell (s)", "Modes", "float",
         0.14, 0.05, 1.50, 0.01,
         tip="Lets the frame stop ringing before the next stroke, and does the "
             "real steering. Tilt cannot move a ball that is in the air, so "
             "the only authority the loop has is the time the ball spends on a "
             "stationary plate - lengthening this is the cheapest way to make "
             "a juggle controllable, at the price of a slower cycle. With the "
             "shipped phases the ball is airborne 13% of the time; it was 23% "
             "at the 25 mm stroke, which was too much to catch."),
]

SPEC_BY_KEY = {s.key: s for s in SPECS}
GROUPS = ("Camera", "Vision", "Control", "Modes", "Machine", "Serial")


class ParameterStore(QObject):
    """Holds every tunable value and announces changes."""

    changed = pyqtSignal(str, object)   # key, new value

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.RLock()
        self._values: Dict[str, Any] = {s.key: s.default for s in SPECS}

    # -- access ------------------------------------------------------------
    def get(self, key: str) -> Any:
        with self._lock:
            return self._values[key]

    def snapshot(self) -> Dict[str, Any]:
        """A consistent copy, so a worker never reads a half-applied preset."""
        with self._lock:
            return dict(self._values)

    def set(self, key: str, value: Any) -> None:
        spec = SPEC_BY_KEY.get(key)
        if spec is not None:
            if spec.kind == "int":
                value = int(round(float(value)))
            elif spec.kind == "float":
                value = float(value)
            elif spec.kind == "bool":
                value = bool(value)
            if spec.kind in ("int", "float"):
                value = max(spec.lo, min(spec.hi, value))
        with self._lock:
            if self._values.get(key) == value:
                return
            self._values[key] = value
        self.changed.emit(key, value)

    # -- presets -----------------------------------------------------------
    def to_json(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.snapshot(), fh, indent=2, sort_keys=True)

    def from_json(self, path: str) -> None:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        for key, value in data.items():
            if key in SPEC_BY_KEY:
                self.set(key, value)
