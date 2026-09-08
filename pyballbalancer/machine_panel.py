"""Machine test panel — the manual moves used to bring the plate up.

These mirror the buttons the Unity editor exposed, because that is the order
the machine has to be checked in: park at the origin first, then prove a pure
height change, then prove each tilt axis separately. Trying to debug a control
loop before those three work is guesswork.

Every action sends one line. Nothing here reads the camera.
"""
from __future__ import annotations

from PyQt5.QtWidgets import (QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                             QPushButton, QTextEdit, QVBoxLayout, QWidget)

import machine


class MachinePanel(QWidget):
    """Manual pose commands, plus a readout of exactly what went on the wire."""

    def __init__(self, params, serial_worker, param_group, blocked=None,
                 on_message=None, parent=None) -> None:
        super().__init__(parent)
        self.params = params
        self.serial = serial_worker
        # Somewhere louder than this panel to repeat every message. A button
        # that refuses has to say so where the user is actually looking; the
        # first version reported only into a small grey label down here, which
        # read as the button doing nothing at all.
        self.on_message = on_message or (lambda text, ok: None)
        self.actions = []
        # Returns a reason string when a manual move would be pointless, or
        # None when it is safe. A running control loop is the case that matters:
        # it commands a pose at the control rate, so anything sent from here is
        # overridden within milliseconds and the button looks broken.
        self.blocked = blocked or (lambda: None)
        layout = QVBoxLayout(self)

        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet(
            "background:#5a2a20;color:#ffd9cf;padding:8px;border-radius:3px;"
            "font-weight:bold;")
        layout.addWidget(self.banner)

        layout.addWidget(param_group)

        # -- step 1: park ------------------------------------------------
        park = QGroupBox("1 — Park")
        pl = QHBoxLayout(park)
        self._button(pl, "Go to ORIGIN", self.go_origin,
                     "Level plate at the working origin. Always start here.")
        self._button(pl, "PING", self.ping, "Liveness check: the firmware answers PONG.")
        layout.addWidget(park)

        # -- levelling trim ----------------------------------------------
        trim = QGroupBox("Level the plate where the loop works")
        tg = QGridLayout(trim)
        tg.addWidget(QLabel("X"), 0, 0)
        self._button_grid(tg, 0, 1, "−", lambda: self._nudge_trim("x", -1))
        self._button_grid(tg, 0, 2, "+", lambda: self._nudge_trim("x", +1))
        tg.addWidget(QLabel("Y"), 1, 0)
        self._button_grid(tg, 1, 1, "−", lambda: self._nudge_trim("y", -1))
        self._button_grid(tg, 1, 2, "+", lambda: self._nudge_trim("y", +1))
        self.lbl_trim = QLabel()
        self.lbl_trim.setStyleSheet("font-family:Consolas;font-size:12px;")
        tg.addWidget(self.lbl_trim, 0, 3, 2, 1)
        self._button_grid(tg, 2, 0, "Reset trim to zero", self._zero_trim, span=2)
        self._button_grid(tg, 2, 2, "Re-send level pose", self.go_trim_height, span=2)
        hint = QLabel(
            "Each nudge holds the plate at the LEVELLING HEIGHT and re-sends "
            "it, so put the ball on the plate and adjust until it stays put "
            "rather than rolling. The ball is the instrument here, not a "
            "spirit level.\n\n"
            "Level at the height the loop actually works at, not at the "
            "origin. The trim on this rig is a property of the height — the "
            "linkage slope changes along its travel — and levelling at the "
            "origin left the ball orbiting 25 mm off centre once the plate "
            "rose to the juggling height, with the controller stuck at 98% of "
            "its tilt limit and juggling unable to resume.\n\n"
            "Trim X first: tilting one pair changes how level the other looks.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#888;font-size:10px;")
        tg.addWidget(hint, 3, 0, 1, 4)
        layout.addWidget(trim)

        # -- step 2: pure height ----------------------------------------
        height = QGroupBox("2 — Height, no tilt")
        hl = QGridLayout(height)
        for col, mm in enumerate((5, 10, 20, 30, 50)):
            btn = QPushButton("%d mm" % mm)
            btn.clicked.connect(lambda _c=False, m=mm: self.go_height(m))
            hl.addWidget(btn, 0, col)
            self.actions.append(btn)
        self._button_grid(hl, 1, 0, "Go to test height", self.go_test_height, span=3)
        self._button_grid(hl, 1, 3, "Up / down cycle", self.oscillate, span=2)
        layout.addWidget(height)

        # -- step 3: tilt ------------------------------------------------
        tilt = QGroupBox("3 — Tilt, at the test height")
        tl = QGridLayout(tilt)
        for col, (label, ax, sign) in enumerate((("X  +", "x", +1), ("X  −", "x", -1),
                                                 ("Y  +", "y", +1), ("Y  −", "y", -1))):
            btn = QPushButton(label)
            btn.clicked.connect(lambda _c=False, a=ax, s=sign: self.go_tilt(a, s))
            tl.addWidget(btn, 0, col)
            self.actions.append(btn)
        self._button_grid(tl, 1, 0, "Tilt sweep  (+X −X +Y −Y, back to level)",
                          self.tilt_sweep, span=4)
        layout.addWidget(tilt)

        self.lbl_last = QLabel("nothing sent yet")
        self.lbl_last.setWordWrap(True)
        self.lbl_last.setMinimumHeight(38)
        layout.addWidget(self.lbl_last)
        self._style_last("#888")

        layout.addWidget(QLabel("Arm angles for the last command"))
        self.txt_angles = QTextEdit()
        self.txt_angles.setReadOnly(True)
        self.txt_angles.setMaximumHeight(112)
        self.txt_angles.setStyleSheet("font-family:Consolas;font-size:10px;")
        layout.addWidget(self.txt_angles)
        layout.addStretch(1)
        self.refresh_trim()

    # ------------------------------------------------------------------
    def _button(self, box, label, slot, tip=""):
        btn = QPushButton(label)
        btn.clicked.connect(slot)
        if tip:
            btn.setToolTip(tip)
        box.addWidget(btn)
        self.actions.append(btn)
        return btn

    def _button_grid(self, grid, row, col, label, slot, span=1):
        btn = QPushButton(label)
        btn.clicked.connect(slot)
        grid.addWidget(btn, row, col, 1, span)
        self.actions.append(btn)
        return btn

    def _style_last(self, colour: str) -> None:
        self.lbl_last.setStyleSheet(
            "font-family:Consolas;font-size:11px;color:%s;" % colour)

    def _report(self, text: str, ok: bool = True) -> None:
        """Say what happened, here and everywhere else that is listening."""
        self._style_last("#8fd18f" if ok else "#e07a5c")
        self.lbl_last.setText(text)
        self.on_message(" ".join(text.split()), ok)

    def set_link_state(self, connected: bool) -> None:
        """Grey the action buttons out when there is nothing to command.

        A disabled button with a reason beside it is honest. An enabled one
        that silently declines is not, and that is exactly how this panel read
        before a port was open: every press did nothing and said so only in a
        10 px grey line at the bottom.
        """
        for btn in self.actions:
            btn.setEnabled(connected)
        self.banner.setVisible(not connected)
        self.banner.setText(
            "" if connected else
            "NOT CONNECTED - open the Serial tab and press Connect. "
            "Until then these buttons do nothing.")

    # ------------------------------------------------------------------
    def _nudge_trim(self, axis: str, sign: int) -> None:
        """Move the trim and immediately show the result on the machine.

        Re-sending origin is the point: the adjustment is made by eye against a
        level, so a change that is not applied until the next command is a
        change you cannot judge.
        """
        key = "mac_trim_%s" % axis
        step = self.params.get("mac_trim_step")
        self.params.set(key, self.params.get(key) + sign * step)
        self.refresh_trim()
        self.go_trim_height()

    def _zero_trim(self) -> None:
        self.params.set("mac_trim_x", 0.0)
        self.params.set("mac_trim_y", 0.0)
        self.refresh_trim()
        self.go_origin()

    def refresh_trim(self) -> None:
        self.lbl_trim.setText("X %+.2f°\nY %+.2f°\nat %.0f mm"
                              % (self.params.get("mac_trim_x"),
                                 self.params.get("mac_trim_y"),
                                 self.params.get("mac_origin_offset")
                                 + self.params.get("mac_trim_height")))

    def _origin_m(self) -> float:
        return self.params.get("mac_origin_offset") / 1000.0

    def _move_time(self) -> float:
        return self.params.get("mac_move_time")

    def _send(self, poses, description: str) -> None:
        """Send, and show both the line and the angles it encodes.

        Displaying the angles matters: if the plate does not move, the first
        question is whether the numbers were wrong or the motors were, and
        this separates those two cases without an oscilloscope.
        """
        if not self.serial.is_open:
            self._report("NOT CONNECTED — open the Serial tab and press Connect",
                         ok=False)
            return
        why = self.blocked()
        if why:
            self._report("IGNORED — %s" % why, ok=False)
            return
        self.serial.send_poses(poses)
        # Show the trimmed poses, because those are what reach the wire. The
        # worker applies the trim itself; displaying the untrimmed command
        # would quietly disagree with the machine.
        shown = machine.apply_trim(poses, self.params.get("mac_trim_x"),
                                   self.params.get("mac_trim_y"))
        line = machine.serialize(
            shown, machine.PAIRINGS.get(self.params.get("mac_motor_order")))
        self._report("%s\n%s" % (description, line))

        report = []
        for height, xt, yt, mt in shown:
            angles = machine.arm_angles(height, xt, yt)
            diffs = [angles[i] - machine.ORIGIN_ANGLES[i] for i in range(4)]
            report.append("h=%6.1f mm  x=%+4.1f°  y=%+4.1f°  t=%.2f s" %
                          (height * 1000, xt, yt, mt))
            report.append("   " + "  ".join(
                "m%d %+7.4f rad %+6d p" % (i, d, machine.pulses_for(d))
                for i, d in enumerate(diffs)))
        self.txt_angles.setPlainText("\n".join(report))

    # -- actions --------------------------------------------------------
    def go_origin(self) -> None:
        self._send([(self._origin_m(), 0.0, 0.0, self._move_time())],
                   "origin — level at the working offset")

    def go_trim_height(self) -> None:
        """Hold the plate where the control loop actually runs, and level there.

        Not the origin. The origin is the one height the ball is never under
        control at - balancing runs 30 mm above it, juggling 35 mm above it -
        and on this machine the trim is a property of the HEIGHT, because the
        linkage carries a residual slope that changes along its travel.
        Levelled at the origin, the ball at the juggling height orbited a point
        25 mm off centre while the loop sat at 98% of its tilt limit, and
        juggling could never resume because the ball was never still.
        """
        height = self._origin_m() + self.params.get("mac_trim_height") / 1000.0
        self._send([(height, 0.0, 0.0, self._move_time())],
                   "levelling pose — %.0f mm above the working origin"
                   % self.params.get("mac_trim_height"))

    def ping(self) -> None:
        if self.serial.is_open:
            self.serial.send_ping()
            self._report("PING sent — expect PONG on the Serial tab")
        else:
            self._report("NOT CONNECTED — open the Serial tab and press Connect",
                         ok=False)

    def go_height(self, mm: float) -> None:
        self._send([(self._origin_m() + mm / 1000.0, 0.0, 0.0, self._move_time())],
                   "height %g mm above the working origin" % mm)

    def go_test_height(self) -> None:
        self.go_height(self.params.get("mac_test_height"))

    def go_tilt(self, axis: str, sign: int) -> None:
        deg = sign * self.params.get("mac_test_tilt")
        h = self._origin_m() + self.params.get("mac_test_height") / 1000.0
        xt, yt = (deg, 0.0) if axis == "x" else (0.0, deg)
        self._send([(h, xt, yt, self._move_time())],
                   "tilt %s %+g° at %g mm" % (axis.upper(), deg,
                                              self.params.get("mac_test_height")))

    def tilt_sweep(self) -> None:
        """One line, five batches: the firmware runs them back to back, so the
        plate traces the whole sweep without the host having to time it."""
        deg = self.params.get("mac_test_tilt")
        h = self._origin_m() + self.params.get("mac_test_height") / 1000.0
        t = self._move_time()
        self._send([(h, +deg, 0.0, t), (h, -deg, 0.0, t),
                    (h, 0.0, +deg, t), (h, 0.0, -deg, t),
                    (h, 0.0, 0.0, t)],
                   "tilt sweep at %g mm" % self.params.get("mac_test_height"))

    def oscillate(self) -> None:
        lo = self._origin_m() + self.params.get("mac_osc_low") / 1000.0
        hi = self._origin_m() + self.params.get("mac_osc_high") / 1000.0
        t = self.params.get("mac_osc_time")
        cycles = int(self.params.get("mac_osc_cycles"))
        # Lead in to the bottom of the stroke first. Without it the plate leaps
        # from wherever it happens to be straight to the top, so the first rise
        # is a different size from every one after it — from the origin that is
        # 30 mm against the 20 mm of the steady stroke, which is exactly the
        # sort of one-off acceleration that shakes the frame.
        poses = [(lo, 0.0, 0.0, t)]
        for _ in range(cycles):
            poses.append((hi, 0.0, 0.0, t))
            poses.append((lo, 0.0, 0.0, t))
        # 100 batches is the firmware's ceiling; two per cycle plus the lead-in
        self._send(poses[:100],
                   "up/down %g↔%g mm, %d cycles at %.2f s per stroke"
                   % (self.params.get("mac_osc_low"), self.params.get("mac_osc_high"),
                      cycles, t))
