"""Reusable GUI pieces: parameter editors built from the spec table, and the
video view.

Editors are generated from params.SPECS rather than hand-written, so adding a
tunable is a one-line change and it cannot be forgotten in the interface.
Binding is two-way, with signals blocked while writing back so a programmatic
update (loading a preset) does not echo round the loop.
"""
from __future__ import annotations

from typing import Dict, Optional

import cv2
import numpy as np
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QImage, QPainter, QPen, QColor, QFont
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                             QHBoxLayout, QLabel, QSlider, QSpinBox, QWidget)

from params import SPECS, ParameterStore, Spec


class ParamRow(QWidget):
    """One parameter: a slider plus a spin box, or a checkbox, or a combo."""

    def __init__(self, spec: Spec, store: ParameterStore, parent=None) -> None:
        super().__init__(parent)
        self.spec, self.store = spec, store
        self._guard = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        if spec.kind == "bool":
            self.editor = QCheckBox()
            self.editor.setChecked(bool(store.get(spec.key)))
            self.editor.toggled.connect(self._push)
            layout.addWidget(self.editor)
            layout.addStretch(1)
        elif spec.kind == "choice":
            self.editor = QComboBox()
            self.set_choices(spec.choices)
            self.editor.currentIndexChanged.connect(self._push)
            layout.addWidget(self.editor, 1)
        else:
            is_int = spec.kind == "int"
            self.slider = QSlider(Qt.Horizontal)
            self._scale = 1.0 if is_int else max(1.0, round(1.0 / spec.step))
            self.slider.setMinimum(int(round(spec.lo * self._scale)))
            self.slider.setMaximum(int(round(spec.hi * self._scale)))
            self.editor = QSpinBox() if is_int else QDoubleSpinBox()
            self.editor.setRange(spec.lo, spec.hi)
            self.editor.setSingleStep(spec.step)
            if not is_int:
                decimals = max(0, len(str(spec.step).split(".")[-1])) if "." in str(spec.step) else 2
                self.editor.setDecimals(min(4, max(2, decimals)))
            self.editor.setFixedWidth(84)
            self.slider.valueChanged.connect(self._from_slider)
            self.editor.valueChanged.connect(self._push)
            layout.addWidget(self.slider, 1)
            layout.addWidget(self.editor)

        if spec.tip:
            self.setToolTip(spec.tip)
        self.refresh(store.get(spec.key))

    # -- choices can change at runtime (serial ports) --------------------
    def set_choices(self, choices) -> None:
        if not isinstance(self.editor, QComboBox):
            return
        self._guard = True
        current = self.store.get(self.spec.key)
        self.editor.clear()
        for c in choices:
            self.editor.addItem(str(c), c)
        idx = self.editor.findData(current)
        if idx < 0:
            idx = self.editor.findText(str(current))
        self.editor.setCurrentIndex(max(0, idx))
        self._guard = False

    # -- store -> widget --------------------------------------------------
    def refresh(self, value) -> None:
        self._guard = True
        if isinstance(self.editor, QCheckBox):
            self.editor.setChecked(bool(value))
        elif isinstance(self.editor, QComboBox):
            idx = self.editor.findData(value)
            if idx < 0:
                idx = self.editor.findText(str(value))
            if idx >= 0:
                self.editor.setCurrentIndex(idx)
        else:
            self.editor.setValue(value)
            self.slider.setValue(int(round(float(value) * self._scale)))
        self._guard = False

    # -- widget -> store --------------------------------------------------
    def _from_slider(self, raw: int) -> None:
        if self._guard:
            return
        self.editor.setValue(raw / self._scale)

    def _push(self, *_args) -> None:
        if self._guard:
            return
        if isinstance(self.editor, QCheckBox):
            value = self.editor.isChecked()
        elif isinstance(self.editor, QComboBox):
            data = self.editor.currentData()
            value = data if data is not None else self.editor.currentText()
        else:
            value = self.editor.value()
            self._guard = True
            self.slider.setValue(int(round(float(value) * self._scale)))
            self._guard = False
        self.store.set(self.spec.key, value)


class ParamGroup(QWidget):
    """Every parameter declared for one group, as a form."""

    def __init__(self, group: str, store: ParameterStore, parent=None) -> None:
        super().__init__(parent)
        self.rows: Dict[str, ParamRow] = {}
        form = QFormLayout(self)
        form.setLabelAlignment(Qt.AlignRight)
        form.setContentsMargins(8, 8, 8, 8)
        for spec in SPECS:
            if spec.group != group:
                continue
            row = ParamRow(spec, store)
            self.rows[spec.key] = row
            form.addRow(spec.label, row)
        store.changed.connect(self._on_changed)

    def _on_changed(self, key: str, value) -> None:
        row = self.rows.get(key)
        if row is not None:
            row.refresh(value)


class VideoView(QWidget):
    """Camera image with the detection overlay drawn on top.

    Clicking sets the control target, which is far quicker than typing
    coordinates while a ball is rolling.
    """

    clicked = pyqtSignal(float, float)      # centre-frame coordinates

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(480, 360)
        self._img: Optional[QImage] = None
        self._det = None
        self._trail: list = []
        self._target = (0.0, 0.0)
        self._tilt = (0.0, 0.0)
        self._shape = (480, 640)
        self.setAutoFillBackground(True)

    def set_target(self, x: float, y: float) -> None:
        self._target = (x, y)

    def set_tilt(self, x: float, y: float) -> None:
        self._tilt = (x, y)

    def update_frame(self, frame: np.ndarray, det, mask) -> None:
        show = mask if mask is not None else frame
        if show.ndim == 2:
            show = cv2.cvtColor(show, cv2.COLOR_GRAY2BGR)
        self._shape = show.shape[:2]
        rgb = cv2.cvtColor(show, cv2.COLOR_BGR2RGB)
        h, w, _ = rgb.shape
        # copy(): the numpy buffer belongs to the capture thread
        self._img = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        self._det = det
        if det is not None:
            self._trail.append((det.px, det.py))
            if len(self._trail) > 90:
                self._trail.pop(0)
        self.update()

    def clear_trail(self) -> None:
        self._trail.clear()

    # ------------------------------------------------------------------
    def _rect(self):
        """Where the image lands inside the widget, preserving aspect."""
        if self._img is None:
            return 0, 0, self.width(), self.height()
        iw, ih = self._img.width(), self._img.height()
        scale = min(self.width() / iw, self.height() / ih)
        w, h = int(iw * scale), int(ih * scale)
        return (self.width() - w) // 2, (self.height() - h) // 2, w, h

    def mousePressEvent(self, event) -> None:
        if self._img is None:
            return
        ox, oy, w, h = self._rect()
        if w <= 0 or h <= 0:
            return
        fx = (event.x() - ox) / w * self._img.width()
        fy = (event.y() - oy) / h * self._img.height()
        self.clicked.emit(fx - self._img.width() / 2.0,
                          self._img.height() / 2.0 - fy)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(24, 24, 26))
        if self._img is None:
            painter.setPen(QColor(150, 150, 150))
            painter.drawText(self.rect(), Qt.AlignCenter, "waiting for camera…")
            return

        ox, oy, w, h = self._rect()
        painter.drawImage(ox, oy, self._img.scaled(w, h, Qt.KeepAspectRatio,
                                                   Qt.SmoothTransformation))
        sx, sy = w / self._img.width(), h / self._img.height()

        def to_widget(px, py):
            return ox + px * sx, oy + py * sy

        # trail
        if len(self._trail) > 1:
            painter.setPen(QPen(QColor(200, 120, 90, 150), 1.6))
            for i in range(1, len(self._trail)):
                x0, y0 = to_widget(*self._trail[i - 1])
                x1, y1 = to_widget(*self._trail[i])
                painter.drawLine(int(x0), int(y0), int(x1), int(y1))

        # target crosshair, in centre-frame coordinates
        cx = self._img.width() / 2.0 + self._target[0]
        cy = self._img.height() / 2.0 - self._target[1]
        tx, ty = to_widget(cx, cy)
        painter.setPen(QPen(QColor(90, 190, 130), 1.6))
        painter.drawLine(int(tx - 12), int(ty), int(tx + 12), int(ty))
        painter.drawLine(int(tx), int(ty - 12), int(tx), int(ty + 12))
        painter.drawEllipse(int(tx - 5), int(ty - 5), 10, 10)

        # detection
        if self._det is not None:
            dx, dy = to_widget(self._det.px, self._det.py)
            r = self._det.radius * sx
            painter.setPen(QPen(QColor(235, 90, 60), 2.0))
            painter.drawEllipse(int(dx - r), int(dy - r), int(2 * r), int(2 * r))
            painter.setPen(QPen(QColor(235, 90, 60), 1.0))
            painter.drawLine(int(dx - 6), int(dy), int(dx + 6), int(dy))
            painter.drawLine(int(dx), int(dy - 6), int(dx), int(dy + 6))
            painter.setFont(QFont("Consolas", 8))
            painter.drawText(int(dx + r + 6), int(dy),
                             "r=%.0f  c=%.2f" % (self._det.radius, self._det.confidence))

        # tilt indicator: an arrow from the frame centre in the commanded
        # direction, so the sign convention is visible at a glance
        mid_x, mid_y = to_widget(self._img.width() / 2.0, self._img.height() / 2.0)
        scale = 8.0
        painter.setPen(QPen(QColor(120, 170, 235), 2.4))
        painter.drawLine(int(mid_x), int(mid_y),
                         int(mid_x + self._tilt[0] * scale),
                         int(mid_y - self._tilt[1] * scale))
        painter.setPen(QColor(150, 150, 150))
        painter.setFont(QFont("Consolas", 8))
        painter.drawText(ox + 6, oy + 14,
                         "tilt %+.2f, %+.2f deg" % self._tilt)
