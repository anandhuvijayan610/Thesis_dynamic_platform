"""CSV recording of everything the loop sees and commands.

One row per control tick, so vision, control and telemetry can be lined up on
a common clock afterwards. Rows are buffered and flushed periodically rather
than per row: at 100 Hz, flushing every write costs more than the control loop
itself.
"""
from __future__ import annotations

import csv
import os
import threading
import time
from typing import List, Optional

COLUMNS = [
    "t_wall", "t_mono",
    "ball_x", "ball_y", "ball_r", "ball_conf",
    "vel_x", "vel_y",
    "cmd_tilt_x", "cmd_tilt_y",
    "ack_tilt_x", "ack_tilt_y", "mcu_loop_hz", "mcu_status",
    "mode", "target_x", "target_y",
]


class DataLogger:
    """Thread-safe CSV writer. Silent no-op until start() is called."""

    FLUSH_EVERY = 1.0       # seconds

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fh = None
        self._writer: Optional[csv.writer] = None
        self._rows: List[list] = []
        self._last_flush = 0.0
        self._path: Optional[str] = None
        self._count = 0

    @property
    def active(self) -> bool:
        return self._fh is not None

    @property
    def path(self) -> Optional[str]:
        return self._path

    @property
    def row_count(self) -> int:
        return self._count

    def start(self, path: str) -> None:
        with self._lock:
            self._stop_locked()
            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
            self._fh = open(path, "w", newline="", encoding="utf-8")
            self._writer = csv.writer(self._fh)
            self._writer.writerow(COLUMNS)
            self._path, self._count = path, 0
            self._last_flush = time.monotonic()

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        if self._fh is not None:
            if self._rows:
                self._writer.writerows(self._rows)
                self._rows.clear()
            self._fh.flush()
            self._fh.close()
        self._fh, self._writer = None, None

    def write(self, row: list) -> None:
        with self._lock:
            if self._writer is None:
                return
            self._rows.append(row)
            self._count += 1
            now = time.monotonic()
            if now - self._last_flush >= self.FLUSH_EVERY:
                self._writer.writerows(self._rows)
                self._rows.clear()
                self._fh.flush()
                self._last_flush = now
