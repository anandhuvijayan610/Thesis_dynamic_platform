"""Ball detection.

Two interchangeable strategies so they can be compared on the same feed:

  ThresholdContour  segment, take the best contour, fit a centre and radius
  HoughCircles      OpenCV's circle transform, kept as the reference

Both return a Detection in image coordinates with the origin at the frame
centre and y pointing up, which is the frame the controller works in. Both
also hand back the binary mask so the GUI can show what the thresholds are
actually selecting — tuning colour ranges blind is the slowest way to do it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np


@dataclass
class Detection:
    """A ball found in one frame."""
    x: float            # px right of frame centre
    y: float            # px above frame centre
    radius: float       # px
    confidence: float   # 0..1
    px: float           # raw pixel column, for drawing
    py: float           # raw pixel row, for drawing


def _to_centre_frame(px: float, py: float, shape) -> Tuple[float, float]:
    h, w = shape[:2]
    return px - w / 2.0, (h / 2.0) - py


def _fit_circle(pts: np.ndarray) -> Tuple[float, float, float]:
    """Least-squares circle through boundary points (Kasa).

    Solves for the circle minimising the algebraic distance; linear, so there
    is nothing to converge and no starting guess to get wrong.
    """
    x = pts[:, 0].astype(np.float64)
    y = pts[:, 1].astype(np.float64)
    a = np.column_stack([x, y, np.ones(len(x))])
    sol, *_ = np.linalg.lstsq(a, x * x + y * y, rcond=None)
    cx, cy = sol[0] / 2.0, sol[1] / 2.0
    return cx, cy, math.sqrt(max(0.0, sol[2] + cx * cx + cy * cy))


def _arc_circle(contour: np.ndarray, shape, margin: float, min_pts: int):
    """Recover the whole ball from the part of it still inside the frame.

    A ball half out of the picture has a useless centroid and a useless
    enclosing circle -- both describe the visible piece, not the ball. Its
    outline, though, still contains a genuine arc of the ball's edge, and an
    arc determines a circle completely. Dropping the boundary points that lie
    along the frame edge (they trace the picture, not the ball) and fitting the
    rest recovers the real centre.

    Measured on this rig: 0.4 px of error with the ball fully visible, 2.0 px
    with 43% of it outside the frame, 2.5 px at 73%. That is what turns the
    camera's narrow band into a usable working area without moving anything.
    """
    pts = contour.reshape(-1, 2)
    h, w = shape[:2]
    on_edge = ((pts[:, 0] <= margin) | (pts[:, 0] >= w - 1 - margin)
               | (pts[:, 1] <= margin) | (pts[:, 1] >= h - 1 - margin))
    if not on_edge.any():
        return None                      # nothing clipped; the normal path is better
    arc = pts[~on_edge]
    # Clipped, so the ordinary measurements are already wrong: from here the
    # answer is either a good arc fit or nothing. Falling back to the enclosing
    # circle would hand back a confident, biased position, which is worse than
    # admitting the ball cannot be located.
    if len(arc) < min_pts:
        return (None, len(arc))
    cx, cy, r = _fit_circle(arc)
    if r <= 1.0:
        return (None, len(arc))
    # A real arc sits on its fitted circle. Anything else -- a straight mask
    # edge, two blobs merged -- does not, and this is what replaces the
    # circularity test, which a clipped ball can never pass.
    resid = float(np.std(np.hypot(arc[:, 0] - cx, arc[:, 1] - cy) - r))
    return (cx, cy, r, resid), len(arc)


def _build_mask(frame: np.ndarray, p: Dict[str, Any]) -> np.ndarray:
    """Isolate the ball. HSV when the ball has a distinct hue, otherwise the
    red-minus-blue difference, which survives a warm, low-saturation scene
    better than a hue gate does."""
    if p["vis_use_hsv"]:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        lo = np.array([p["vis_h_lo"], p["vis_s_lo"], p["vis_v_lo"]], np.uint8)
        hi = np.array([p["vis_h_hi"], p["vis_s_hi"], p["vis_v_hi"]], np.uint8)
        if p["vis_h_lo"] <= p["vis_h_hi"]:
            mask = cv2.inRange(hsv, lo, hi)
        else:
            # hue wraps at 180, so a red band needs two ranges unioned
            lo1 = np.array([0, p["vis_s_lo"], p["vis_v_lo"]], np.uint8)
            hi1 = np.array([p["vis_h_hi"], p["vis_s_hi"], p["vis_v_hi"]], np.uint8)
            lo2 = np.array([p["vis_h_lo"], p["vis_s_lo"], p["vis_v_lo"]], np.uint8)
            hi2 = np.array([179, p["vis_s_hi"], p["vis_v_hi"]], np.uint8)
            mask = cv2.inRange(hsv, lo1, hi1) | cv2.inRange(hsv, lo2, hi2)
    else:
        b, _g, r = cv2.split(frame)
        diff = cv2.subtract(r, b)
        _, mask = cv2.threshold(diff, p["vis_diff_thresh"], 255, cv2.THRESH_BINARY)

    k = int(p["vis_kernel"])
    if k > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return mask


class ThresholdContour:
    """Segment, then score every candidate contour.

    Every plausible contour is returned, not just the best one. Which of them
    is the ball is a question about continuity between frames, and a single
    frame cannot answer it — see BallTracker.
    """

    name = "Threshold + contour"

    def __init__(self) -> None:
        # Why the largest blobs were turned down, most recent frame. "No ball"
        # on its own is the least useful answer a detector can give: every
        # cause looks identical from outside, and working out which one it was
        # otherwise means attaching a script to the running application.
        self.rejections: List[str] = []

    def candidates(self, frame, p) -> Tuple[List[Detection], Optional[np.ndarray]]:
        mask = _build_mask(frame, p)
        # CHAIN_APPROX_NONE, not SIMPLE: the arc fit needs every boundary
        # point, and SIMPLE throws most of them away by collapsing straight
        # runs -- which is exactly what a clipped ball's outline is made of.
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)

        found: List[Detection] = []
        notes = []
        if not contours:
            # Distinct from every other cause: nothing survived the colour
            # gate and morphology at all, so the thresholds are the place to
            # look, not the shape filters.
            self.rejections = ["nothing passed the colour gate "
                               "(check hue/saturation/value, or the kernel)"]
            return found, mask
        for c in sorted(contours, key=cv2.contourArea, reverse=True)[:6]:
            area = cv2.contourArea(c)
            perim = cv2.arcLength(c, True)
            (cx, cy), enc_r = cv2.minEnclosingCircle(c)
            # 4*pi*A/P^2 is 1 for a disc and falls away for anything
            # elongated. It is also very sensitive to a ragged mask edge, and
            # that is not a theoretical worry here: when the ball's shaded limb
            # sits near the brightness floor its outline serrates, the
            # perimeter inflates, and a perfectly round blob scores 0.43 where
            # the same ball in even light scores 0.88. It is therefore a loose
            # backstop, not the gate that decides -- see fill below.
            circ = 4.0 * math.pi * area / (perim * perim) if perim > 0 else 0.0
            # area-equivalent radius agrees with the enclosing circle for a
            # whole ball and is smaller for a clipped one. The ratio is both a
            # cheap partial-occlusion check and the roundness measure this
            # actually gates on: it asks how well the shape packs a disc, which
            # is the same question circularity asks, but answers it from area
            # alone and so cannot be spoiled by a noisy boundary.
            area_r = math.sqrt(area / math.pi) if area > 0 else 0.0
            fill = min(1.0, area_r / enc_r) if enc_r > 0 else 0.0

            # A contour touching the frame edge is a partly-visible ball;
            # judge it by an arc fit rather than by shape tests it cannot pass.
            clipped = _arc_circle(c, frame.shape, p["vis_edge_margin"],
                                  int(p["vis_min_arc_points"]))
            if clipped is not None:
                fit, npts = clipped
                if fit is None:
                    notes.append("too little of the ball inside the frame to "
                                 "reconstruct (%d arc points, %d needed)"
                                 % (npts, int(p["vis_min_arc_points"])))
                    continue
                acx, acy, ar, resid = fit
                if resid > p["vis_max_arc_residual"]:
                    notes.append("edge blob is not a circular arc "
                                 "(residual %.1f px over %d points)" % (resid, npts))
                    continue
                if not (p["vis_min_radius"] <= ar <= p["vis_max_radius"]):
                    notes.append("edge blob radius %.0f px outside %d..%d"
                                 % (ar, p["vis_min_radius"], p["vis_max_radius"]))
                    continue
                x, y = _to_centre_frame(acx, acy, frame.shape)
                found.append(Detection(x, y, ar, max(0.0, 1.0 - resid / 10.0),
                                       acx, acy))
                continue

            why = None
            if area < p["vis_min_area"]:
                why = "too small (area %.0f < %d)" % (area, p["vis_min_area"])
            elif area > p["vis_max_area"]:
                why = "too large (area %.0f > %d)" % (area, p["vis_max_area"])
            elif fill < p["vis_min_fill"]:
                why = ("not round enough (fill %.2f < %.2f, circularity %.2f)"
                       % (fill, p["vis_min_fill"], circ))
            elif circ < p["vis_min_circularity"]:
                why = ("outline too straggly (circularity %.2f < %.2f, "
                       "fill %.2f)" % (circ, p["vis_min_circularity"], fill))
            elif not (p["vis_min_radius"] <= area_r <= p["vis_max_radius"]):
                why = ("radius %.0f px outside %d..%d"
                       % (area_r, p["vis_min_radius"], p["vis_max_radius"]))

            if why is not None:
                notes.append(why)
                continue

            x, y = _to_centre_frame(cx, cy, frame.shape)
            # Confidence ranks candidates against each other, so it uses the
            # measure that does not swing with edge noise: a ragged real ball
            # must not be ranked below a smooth-edged piece of clutter.
            found.append(Detection(x, y, area_r, min(1.0, fill), cx, cy))

        self.rejections = notes
        return found, mask


class HoughCircles:
    """OpenCV's circle transform, on the same mask for a fair comparison."""

    name = "HoughCircles"

    def __init__(self) -> None:
        self.rejections: List[str] = []

    def candidates(self, frame, p) -> Tuple[List[Detection], Optional[np.ndarray]]:
        mask = _build_mask(frame, p)
        blurred = cv2.medianBlur(mask, 5)
        circles = cv2.HoughCircles(
            blurred, cv2.HOUGH_GRADIENT,
            dp=float(p["vis_hough_dp"]),
            minDist=float(p["vis_hough_mindist"]),
            param1=float(p["vis_hough_p1"]),
            param2=float(p["vis_hough_p2"]),
            minRadius=int(p["vis_min_radius"]),
            maxRadius=int(p["vis_max_radius"]),
        )
        if circles is None or len(circles[0]) == 0:
            return [], mask

        yy, xx = np.ogrid[:mask.shape[0], :mask.shape[1]]
        found: List[Detection] = []
        for cx, cy, r in circles[0]:
            x, y = _to_centre_frame(float(cx), float(cy), frame.shape)
            # the transform gives no quality figure, so report how well the
            # mask actually fills the circle it claims to have found
            disc = (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r
            filled = (float(np.count_nonzero(mask[disc]))
                      / max(1.0, float(np.count_nonzero(disc))))
            found.append(Detection(x, y, float(r), filled, float(cx), float(cy)))
        self.rejections = []
        return found, mask


STRATEGIES = {s.name: s for s in (ThresholdContour(), HoughCircles())}


class BallTracker:
    """Decides which candidate is the ball, and declines to guess.

    A single frame cannot say which blob is the ball. A ball whose bright side
    falls outside the colour gate breaks into several contours, and background
    clutter can be rounder than any of them. Continuity between frames can say,
    and that is the whole design.

    Two things shape it. "Take the biggest plausible blob" is not safe at cold
    start, because whatever it picks is then defended: a proximity gate to the
    last accepted position keeps a stationary mistake accepted forever, since
    something that never moves always looks like the same thing, still nearby.
    So the lock must be *earned* before it is trusted. And the strongest
    evidence available is geometric — the ball is on the plate and the plate is
    centred in the frame, so anything far outside that region cannot be the
    ball however round it looks.

    Hence: reject anything outside the plate region, require a new candidate to
    hold still for a few frames before trusting it, then track it by proximity
    and drop the lock after enough consecutive misses.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._locked: Optional[Detection] = None
        self._misses = 0
        self._pending: Optional[Detection] = None
        self._pending_frames = 0

    @property
    def locked(self) -> bool:
        return self._locked is not None

    @property
    def pending_frames(self) -> int:
        return self._pending_frames

    def select(self, candidates: List[Detection], p) -> Optional[Detection]:
        roi = float(p["vis_roi_radius"])
        inside = [c for c in candidates if math.hypot(c.x, c.y) <= roi]

        if self._locked is not None:
            gate = float(p["vis_gate_px"])
            # Size continuity, for the same reason as position continuity. A
            # ball's radius changes only slowly, with height; a sudden drop
            # means the blob is a fragment of it -- clipped by the frame edge,
            # or split by the logo printed on it. Such a fragment reports a
            # centre pulled toward whatever part still shows, and because it
            # also reports a *smaller* radius it slips past a guard that tests
            # the radius it claims to have.
            grow = float(p["vis_radius_tolerance"])
            near = [c for c in inside
                    if math.hypot(c.x - self._locked.x, c.y - self._locked.y) <= gate
                    and grow * self._locked.radius <= c.radius
                    <= self._locked.radius / max(1e-3, grow)]
            if near:
                self._locked = min(near, key=lambda c: math.hypot(c.x - self._locked.x,
                                                                  c.y - self._locked.y))
                self._misses = 0
                return self._locked
            self._misses += 1
            if self._misses >= int(p["vis_gate_frames"]):
                # long enough gone that this is a different situation, not the
                # same ball briefly hidden; start looking from scratch
                self.reset()
            return None

        if not inside:
            self._pending, self._pending_frames = None, 0
            return None

        # Cold start. Prefer the candidate nearest the middle of the plate over
        # the largest one: a ball is far more likely to be near the centre than
        # edge clutter is, and size is exactly the cue that picks the ceiling.
        pick = min(inside, key=lambda c: math.hypot(c.x, c.y))

        if (self._pending is not None
                and math.hypot(pick.x - self._pending.x,
                               pick.y - self._pending.y) <= float(p["vis_lock_tol_px"])):
            self._pending_frames += 1
        else:
            self._pending_frames = 1
        self._pending = pick

        if self._pending_frames >= int(p["vis_lock_frames"]):
            self._locked = pick
            self._misses = 0
            return pick
        # Not yet trusted. "No ball" is the safe answer: every caller already
        # treats it as wait-and-do-nothing.
        return None


class VisionProcessor:
    """Runs the selected strategy, then decides which candidate to believe."""

    def __init__(self) -> None:
        self._fallback = ThresholdContour()
        self.tracker = BallTracker()
        self.rejections: List[str] = []

    def reset(self) -> None:
        self.tracker.reset()

    def process(self, frame, params) -> Tuple[Optional[Detection], Optional[np.ndarray]]:
        strategy = STRATEGIES.get(params.get("vis_strategy"), self._fallback)
        try:
            found, mask = strategy.candidates(frame, params)
        except cv2.error:
            # a bad parameter combination should degrade to "no ball", never
            # take the capture thread down
            return None, None
        # Clipped balls are no longer thrown away: the strategy recovers their
        # centre by fitting a circle to the arc still inside the frame, which
        # is what lets the ball work well outside the band where it is wholly
        # visible. The old guard dropped them because a clipped centroid is
        # biased -- true of a centroid, not of an arc fit.
        det = self.tracker.select(found, params)
        self.rejections = list(getattr(strategy, "rejections", []))
        if det is None and found:
            roi = float(params["vis_roi_radius"])
            outside = [c for c in found if math.hypot(c.x, c.y) > roi]
            if len(outside) == len(found):
                self.rejections.append(
                    "%d blob(s) found but all outside the %d px plate region "
                    "(nearest %.0f px out)"
                    % (len(found), int(roi),
                       min(math.hypot(c.x, c.y) for c in found)))
            elif not self.tracker.locked:
                self.rejections.append(
                    "holding still for %d of %d frames before trusting it"
                    % (self.tracker.pending_frames, int(params["vis_lock_frames"])))
        return det, mask
