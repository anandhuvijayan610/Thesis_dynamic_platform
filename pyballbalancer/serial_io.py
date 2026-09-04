"""Serial link to the Teensy running the SineStepper firmware.

The firmware's protocol is not a command language — it is one line of
colon-separated doubles, six per move batch:

    <marker>:<a0>:<a1>:<a2>:<a3>:<move_time>\\n

marker = 11.0 x batch number (1-based); the four values are arm angles in
radians as a difference from the origin pose; move_time is seconds and is
clamped up to the firmware's 0.05 s floor. Batches may be concatenated, up to
100 per line.

There is no STOP or HOME verb: the firmware knows only poses. "Home" is
therefore a move to the origin pose, and the emergency stop is the same move
with a short duration. The one exception is PING, which the firmware answers
with PONG before it reaches the parser — the only liveness check available.

A malformed line is not rejected loudly. strtok/atof yield zero batches and
the firmware does nothing at all, so a protocol mismatch looks exactly like
dead motors.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import serial
from serial.tools import list_ports
from PyQt5.QtCore import QThread, pyqtSignal

import machine

Pose = Tuple[float, float, float, float]      # height_m, x_tilt_deg, y_tilt_deg, move_time_s


@dataclass
class Telemetry:
    ack_x: float
    ack_y: float
    loop_hz: float
    status: str
    t: float


def available_ports() -> List[str]:
    return [p.device for p in list_ports.comports()]


class SerialWorker(QThread):
    """Owns the port. Nothing else touches pyserial."""

    telemetry = pyqtSignal(object)
    line_received = pyqtSignal(str)
    line_sent = pyqtSignal(str)
    connection_changed = pyqtSignal(bool, str)
    pong = pyqtSignal(float)                 # round-trip seconds

    def __init__(self, params=None) -> None:
        super().__init__()
        # Held rather than copied so the levelling trim is always the current
        # one. A cached copy kept in step by a setter is exactly the thing that
        # goes stale without anyone noticing.
        self._params = params
        self._running = False
        self._port: Optional[serial.Serial] = None
        self._lock = threading.Lock()
        self._want: Optional[tuple] = None
        self._disconnect = False
        self._pending_pose: Optional[Sequence[Pose]] = None
        self._pending_raw: List[str] = []
        self._ping_sent: Optional[float] = None

    # -- called from the GUI / control threads -------------------------
    def connect_to(self, port: str, baud: int) -> None:
        with self._lock:
            self._want = (port, int(baud))
            self._disconnect = False

    def disconnect_from(self) -> None:
        with self._lock:
            self._want = None
            self._disconnect = True

    def send_poses(self, poses: Sequence[Pose]) -> None:
        """Queue a move. Newest wins — a stale pose is worse than none."""
        with self._lock:
            self._pending_pose = list(poses)

    def send_pose(self, height_m: float, x_tilt: float, y_tilt: float,
                  move_time: float) -> None:
        self.send_poses([(height_m, x_tilt, y_tilt, move_time)])

    def trim(self):
        """Mechanical levelling offset, degrees, as (x, y)."""
        if self._params is None:
            return 0.0, 0.0
        return self._params.get("mac_trim_x"), self._params.get("mac_trim_y")

    def pairing(self):
        """Which computed arm drives which physical motor."""
        if self._params is None:
            return None
        return machine.PAIRINGS.get(self._params.get("mac_motor_order"))

    def send_ping(self) -> None:
        with self._lock:
            self._pending_raw.append("PING")
            self._ping_sent = time.monotonic()

    def send_raw(self, line: str) -> None:
        """Send a line verbatim.

        For pasting a wire line captured from Unity, or a deliberately bad one
        to make the firmware talk back. Queued rather than written here so that
        only the worker thread ever touches the port.
        """
        with self._lock:
            self._pending_raw.append(line.strip())

    def stop(self) -> None:
        self._running = False
        self.wait(2000)

    @property
    def is_open(self) -> bool:
        return self._port is not None and self._port.is_open

    # -- worker ---------------------------------------------------------
    def _open(self, port: str, baud: int) -> None:
        try:
            self._port = serial.Serial(port, baud, timeout=0.01, write_timeout=0.5)
            # The Teensy ignores the baud rate outright — USB CDC always runs
            # at full speed — so a mismatch here cannot be the fault. It does
            # not reset when the port opens either, so it carries on doing
            # whatever it was already doing. DTR is asserted explicitly because
            # some hosts leave it low, and the first bytes after enumeration
            # are unreliable, so they are discarded.
            self._port.dtr = True
            time.sleep(0.2)
            self._port.reset_input_buffer()
            with self._lock:
                # Drop anything queued before this port existed, so a stale
                # command cannot fire as a surprise move the moment we connect.
                self._pending_pose, self._pending_raw = None, []
            self.connection_changed.emit(True, "connected to %s at %d baud" % (port, baud))
        except (serial.SerialException, OSError) as exc:
            self._port = None
            self.connection_changed.emit(False, "could not open %s: %s" % (port, exc))

    def _close(self, why: str) -> None:
        if self._port is not None:
            try:
                self._port.close()
            except (serial.SerialException, OSError):
                pass
        self._port = None
        self.connection_changed.emit(False, why)

    def _write(self, line: str) -> None:
        """Put one line on the wire and announce it.

        The flush matters: without it the line can sit in the OS buffer while
        the plate does nothing, which reads as a dead link. Announcing every
        line is what makes the difference between the firmware being silent
        (normal — it only answers PING) and the host never having sent
        anything (a fault) visible on screen.
        """
        payload = (line + "\n").encode("ascii")
        written = self._port.write(payload)
        self._port.flush()
        if written not in (None, len(payload)):
            self.line_received.emit("short write: %s of %s bytes"
                                    % (written, len(payload)))
        self.line_sent.emit(line)

    def run(self) -> None:
        self._running = True
        buf = b""

        while self._running:
            with self._lock:
                want, disconnect = self._want, self._disconnect

            if disconnect and self.is_open:
                self._close("disconnected")
            if want is not None and not self.is_open:
                self._open(*want)
                with self._lock:
                    self._want = None

            if not self.is_open:
                # Anything queued stays queued. Draining it here would swallow
                # a command issued between the click and the port finishing
                # opening, and a swallowed command is indistinguishable from a
                # dead link.
                self.msleep(50)
                continue

            with self._lock:
                poses, raws = self._pending_pose, self._pending_raw
                self._pending_pose, self._pending_raw = None, []

            try:
                for raw in raws:
                    self._write(raw)
                if poses:
                    # The one place the trim is applied. Every pose bound for
                    # the wire passes through here, so it cannot be applied
                    # twice or forgotten at one of the several call sites that
                    # build poses.
                    tx, ty = self.trim()
                    self._write(machine.serialize(
                        machine.apply_trim(poses, tx, ty), self.pairing()))

                waiting = self._port.in_waiting
                if waiting:
                    buf += self._port.read(waiting)
                    while b"\n" in buf:
                        chunk, buf = buf.split(b"\n", 1)
                        self._handle(chunk.decode("ascii", "replace").strip())
            except (serial.SerialException, OSError) as exc:
                self._close("link lost: %s" % exc)
                buf = b""
                continue

            self.msleep(2)

        if self.is_open:
            self._close("shut down")

    def _handle(self, line: str) -> None:
        if not line:
            return
        if line == "PONG":
            with self._lock:
                sent, self._ping_sent = self._ping_sent, None
            self.pong.emit(time.monotonic() - sent if sent else 0.0)
            return
        if line.startswith("TELEM,"):
            parts = line.split(",")
            try:
                self.telemetry.emit(Telemetry(float(parts[1]), float(parts[2]),
                                              float(parts[3]),
                                              parts[4] if len(parts) > 4 else "",
                                              time.monotonic()))
                return
            except (IndexError, ValueError):
                pass
        self.line_received.emit(line)
