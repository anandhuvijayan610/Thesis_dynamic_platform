"""Camera capture and per-frame detection, on their own thread.

Detection runs here rather than on a separate thread because the control loop
wants the newest ball position, not every ball position; queueing frames to a
second worker would only add latency and a backlog to drain. The GUI is kept
responsive by throttling how often frames are emitted for display, while
detections are emitted for every frame.
"""
from __future__ import annotations

import platform
import time
from typing import Optional

import cv2
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

from vision import Detection, VisionProcessor

# Windows: DirectShow honours exposure/gain writes, which the Media Foundation
# backend silently ignores on many UVC cameras.
_BACKEND = cv2.CAP_DSHOW if platform.system() == "Windows" else cv2.CAP_V4L2

# Properties pushed to the device, in the order they must be applied: the
# auto-exposure mode has to be set before a manual exposure value will stick.
_CONTROLS = (
    ("cam_auto_exposure", cv2.CAP_PROP_AUTO_EXPOSURE),
    ("cam_exposure", cv2.CAP_PROP_EXPOSURE),
    ("cam_gain", cv2.CAP_PROP_GAIN),
    ("cam_brightness", cv2.CAP_PROP_BRIGHTNESS),
    ("cam_saturation", cv2.CAP_PROP_SATURATION),
    ("cam_contrast", cv2.CAP_PROP_CONTRAST),
)


class CameraWorker(QThread):
    """Grabs frames, detects the ball, reports both."""

    frame_ready = pyqtSignal(object, object, object)   # frame, Detection|None, mask|None
    detection = pyqtSignal(object, float)              # Detection|None, monotonic timestamp
    fps_measured = pyqtSignal(float)
    status = pyqtSignal(str)

    def __init__(self, params, display_hz: float = 30.0) -> None:
        super().__init__()
        self._params = params
        self._vision = VisionProcessor()
        self._running = False
        self._display_interval = 1.0 / display_hz
        self._reopen = True          # set whenever a device/format change lands
        self._pending_controls = True
        params.changed.connect(self._on_param_changed)

    # ------------------------------------------------------------------
    def _on_param_changed(self, key: str, _value) -> None:
        if key in ("cam_index", "cam_width", "cam_height", "cam_fps"):
            self._reopen = True        # format changes need the device reopened
        elif key.startswith("cam_"):
            self._pending_controls = True

    def reset_tracking(self) -> None:
        """Forget which blob was the ball.

        Called when a run starts, so a lock earned while the rig was idle -- on
        a hand, or on the ceiling -- is not inherited by the control loop.
        """
        self._vision.reset()

    def stop(self) -> None:
        self._running = False
        self.wait(2000)

    # ------------------------------------------------------------------
    def _open(self, p) -> Optional[cv2.VideoCapture]:
        cap = cv2.VideoCapture(int(p["cam_index"]), _BACKEND)
        if not cap.isOpened():
            cap.release()
            return None
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(p["cam_width"]))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(p["cam_height"]))
        cap.set(cv2.CAP_PROP_FPS, int(p["cam_fps"]))
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.status.emit("camera %d open, delivering %dx%d" % (p["cam_index"], w, h))
        return cap

    def _apply_controls(self, cap, p) -> None:
        for key, prop in _CONTROLS:
            value = p[key]
            if key == "cam_auto_exposure":
                # this camera family uses 1 = auto, 0 = manual on both backends
                value = 1.0 if value else 0.0
            cap.set(prop, float(value))

    # ------------------------------------------------------------------
    def run(self) -> None:
        self._running = True
        cap: Optional[cv2.VideoCapture] = None
        last_display = 0.0
        frames, window_start = 0, time.monotonic()

        while self._running:
            p = self._params.snapshot()

            if self._reopen or cap is None:
                if cap is not None:
                    cap.release()
                cap = self._open(p)
                self._reopen = False
                self._pending_controls = True
                if cap is None:
                    self.status.emit("camera %d unavailable — retrying" % p["cam_index"])
                    # sleep in the worker, never on the GUI thread
                    self.msleep(700)
                    continue

            if self._pending_controls:
                self._apply_controls(cap, p)
                self._pending_controls = False

            ok, frame = cap.read()
            if not ok or frame is None:
                self.status.emit("frame grab failed — reopening")
                self._reopen = True
                self.msleep(200)
                continue

            now = time.monotonic()
            det, mask = self._vision.process(frame, p)
            self.detection.emit(det, now)

            frames += 1
            if now - window_start >= 0.5:
                self.fps_measured.emit(frames / (now - window_start))
                frames, window_start = 0, now

            # Display is throttled independently of capture: the control loop
            # gets every frame, the screen gets as many as it can paint.
            if now - last_display >= self._display_interval:
                last_display = now
                self.frame_ready.emit(frame, det, mask if p["vis_show_mask"] else None)

        if cap is not None:
            cap.release()
        self.status.emit("camera stopped")
