"""Main window: assembles the panels, owns the workers, wires the signals.

No control or vision maths lives here. The window's job is to start threads,
route signals between them, and keep the display honest about what the machine
is doing.
"""
from __future__ import annotations

import math
import os
import time
from collections import deque
from typing import Optional

import pyqtgraph as pg
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (QComboBox, QFileDialog, QGroupBox, QHBoxLayout,
                             QLabel, QLineEdit, QMainWindow, QMessageBox,
                             QPushButton,
                             QShortcut, QSplitter, QStatusBar, QTabWidget,
                             QTextEdit, QVBoxLayout, QWidget)

import machine
import optics
from camera import CameraWorker
from control import ControlLoop
from datalog import DataLogger
from machine_panel import MachinePanel
from modes import (BALANCE_JUGGLE, BALANCE_REST, BALANCING, JUGGLING,
                   ModeRunner)
from params import GROUPS, ParameterStore
from serial_io import SerialWorker, available_ports
from widgets import ParamGroup, VideoView

PLOT_SPAN = 600     # samples held in each plot, ~6 s at 100 Hz


def _escape(text: str) -> str:
    """The monitor renders HTML, and a raw line must not be read as markup."""
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


class MainWindow(QMainWindow):

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Ball Balancer — control and tuning")
        self.resize(1500, 950)

        self.params = ParameterStore()
        self.logger = DataLogger()
        self.modes = ModeRunner(self.params)

        # -- state mirrored for the plots and the CSV --------------------
        self._t0 = time.monotonic()
        self._state = None
        self._cmd = (0.0, 0.0)
        self._telem = None
        self._estopped = False
        # What the plate was last told to do, so the measured ball size can
        # be sanity-checked against the distance it implies.
        self._commanded_height = self.params.get("mac_origin_offset") / 1000.0
        # The control loop ticks and emits a tilt whether or not it is armed,
        # because the plots and the video overlay want every tick. Only an
        # armed loop may write to the port, though: an idle one would otherwise
        # flood it with a level pose at the command rate, and since the firmware
        # clears its queued batches on every line received, that stream cancels
        # any multi-batch move the Machine tab sends a few milliseconds later.
        self._armed = False
        self._buf = {k: deque(maxlen=PLOT_SPAN) for k in
                     ("t", "bx", "by", "cx", "cy", "ax", "ay", "vhz", "chz")}

        # The Machine and Serial panels wire buttons straight to the serial
        # worker, so it has to exist before the UI is built. Starting the
        # threads stays separate, and happens once everything is connected.
        self.camera = CameraWorker(self.params)
        self.control = ControlLoop(self.params)
        self.serial = SerialWorker(self.params)

        self._build_ui()
        self._start_workers()

    # ==================================================================
    def _build_ui(self) -> None:
        self.video = VideoView()
        self.video.clicked.connect(self._on_video_clicked)

        tabs = QTabWidget()
        self.groups = {}
        for name in GROUPS:
            group = ParamGroup(name, self.params)
            self.groups[name] = group
            if name == "Serial":
                tabs.addTab(self._serial_tab(group), name)
            elif name == "Machine":
                self.machine_panel = MachinePanel(self.params, self.serial, group,
                                                  blocked=self._machine_blocked,
                                                  on_message=self._on_machine_message)
                tabs.addTab(self.machine_panel, name)
            else:
                tabs.addTab(group, name)
        tabs.addTab(self._session_tab(), "Session")
        tabs.setMinimumWidth(430)

        upper = QSplitter(Qt.Horizontal)
        upper.addWidget(self.video)
        upper.addWidget(tabs)
        upper.setStretchFactor(0, 3)
        upper.setStretchFactor(1, 2)

        outer = QSplitter(Qt.Vertical)
        outer.addWidget(upper)
        outer.addWidget(self._plots())
        outer.setStretchFactor(0, 3)
        outer.setStretchFactor(1, 1)
        self.setCentralWidget(outer)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("ready")

        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self._emergency_stop)
        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self._emergency_stop)

        self._ui_timer = QTimer(self)
        self._ui_timer.timeout.connect(self._refresh_readouts)
        self._ui_timer.start(100)

        self._plot_timer = QTimer(self)
        self._plot_timer.timeout.connect(self._refresh_plots)
        self._plot_timer.start(50)

    # ------------------------------------------------------------------
    def _serial_tab(self, group: ParamGroup) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(group)

        row = QHBoxLayout()
        self.btn_refresh_ports = QPushButton("Refresh ports")
        self.btn_refresh_ports.clicked.connect(self._refresh_ports)
        self.btn_connect = QPushButton("Connect")
        self.btn_connect.clicked.connect(self._toggle_serial)
        row.addWidget(self.btn_refresh_ports)
        row.addWidget(self.btn_connect)
        box.addLayout(row)

        self.lbl_conn = QLabel("● disconnected")
        self.lbl_conn.setStyleSheet("color:#b3452c;font-weight:bold;")
        box.addWidget(self.lbl_conn)

        # The firmware has no HOME or STOP verb; it understands poses and
        # nothing else. Both are therefore a move to the level origin. PING is
        # the one true command, answered before the parser sees the line, so it
        # is the only way to tell a live board from a silent one.
        cmds = QHBoxLayout()
        btn_home = QPushButton("Go to ORIGIN")
        btn_home.clicked.connect(self._go_origin)
        cmds.addWidget(btn_home)
        btn_ping = QPushButton("PING")
        btn_ping.clicked.connect(lambda: self.serial.send_ping())
        cmds.addWidget(btn_ping)
        box.addLayout(cmds)

        note = QLabel(
            "The firmware is built with VERBOSE_SERIAL_LOGGING off, so it "
            "answers PING and otherwise says nothing at all. Silence after a "
            "move is normal and is not evidence of a fault — use PING, and "
            "watch the TX lines below to confirm the host is sending.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#888;font-size:10px;")
        box.addWidget(note)

        raw = QHBoxLayout()
        self.edit_raw = QLineEdit()
        self.edit_raw.setPlaceholderText(
            "raw line, e.g. 11.00000:0.10000:0.00000:0.00000:0.00000:2.00000")
        self.edit_raw.setStyleSheet("font-family:Consolas;font-size:10px;")
        self.edit_raw.returnPressed.connect(self._send_raw_line)
        btn_raw = QPushButton("Send")
        btn_raw.clicked.connect(self._send_raw_line)
        raw.addWidget(self.edit_raw)
        raw.addWidget(btn_raw)
        box.addLayout(raw)

        box.addWidget(QLabel("Serial monitor  (TX = sent, RX = received)"))
        self.txt_telem = QTextEdit()
        self.txt_telem.setReadOnly(True)
        self.txt_telem.setMinimumHeight(220)
        self.txt_telem.setStyleSheet(
            "font-family:Consolas;font-size:11px;background:#1b1b1d;")
        box.addWidget(self.txt_telem, 1)
        return page

    def _session_tab(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)

        run = QGroupBox("Run")
        rl = QVBoxLayout(run)

        pick = QHBoxLayout()
        pick.addWidget(QLabel("Mode"))
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems([BALANCING, BALANCE_REST, BALANCE_JUGGLE,
                                JUGGLING])
        self.cmb_mode.setCurrentText(self.params.get("mod_mode"))
        self.cmb_mode.currentTextChanged.connect(
            lambda t: self.params.set("mod_mode", t))
        pick.addWidget(self.cmb_mode, 1)
        rl.addLayout(pick)

        self.lbl_mode = QLabel()
        self.lbl_mode.setWordWrap(True)
        self.lbl_mode.setStyleSheet("color:#999;font-size:10px;")
        rl.addWidget(self.lbl_mode)

        self.btn_run = QPushButton("Start")
        self.btn_run.setCheckable(True)
        self.btn_run.setStyleSheet("padding:10px;font-weight:bold;")
        self.btn_run.toggled.connect(self._toggle_control)
        rl.addWidget(self.btn_run)

        self.lbl_phase = QLabel("stopped")
        self.lbl_phase.setStyleSheet(
            "font-family:Consolas;font-size:13px;font-weight:bold;color:#8fd18f;")
        rl.addWidget(self.lbl_phase)

        self.btn_estop = QPushButton("EMERGENCY STOP  (Esc / Space)")
        self.btn_estop.setStyleSheet(
            "background-color:#b3452c;color:white;font-weight:bold;padding:14px;")
        self.btn_estop.clicked.connect(self._emergency_stop)
        rl.addWidget(self.btn_estop)
        box.addWidget(run)

        pre = QGroupBox("Presets")
        pl = QVBoxLayout(pre)
        self.cmb_presets = QComboBox()
        self.cmb_presets.activated.connect(self._load_recent_preset)
        pl.addWidget(self.cmb_presets)
        prow = QHBoxLayout()
        for label, slot in (("Save…", self._save_preset), ("Load…", self._load_preset)):
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            prow.addWidget(btn)
        pl.addLayout(prow)
        box.addWidget(pre)

        log = QGroupBox("Data logging")
        ll = QVBoxLayout(log)
        self.btn_log = QPushButton("Start CSV logging…")
        self.btn_log.setCheckable(True)
        self.btn_log.toggled.connect(self._toggle_logging)
        ll.addWidget(self.btn_log)
        self.lbl_log = QLabel("not recording")
        ll.addWidget(self.lbl_log)
        box.addWidget(log)

        self.lbl_readout = QLabel()
        self.lbl_readout.setStyleSheet("font-family:Consolas;font-size:11px;")
        self.lbl_readout.setAlignment(Qt.AlignTop)
        box.addWidget(self.lbl_readout)
        box.addStretch(1)
        return page

    def _plots(self) -> QWidget:
        pg.setConfigOptions(antialias=False, background="#1b1b1d", foreground="#c8c8c8")
        panel = QWidget()
        row = QHBoxLayout(panel)
        row.setContentsMargins(4, 4, 4, 4)

        self.p_pos = pg.PlotWidget(title="ball position (px from centre)")
        self.c_bx = self.p_pos.plot(pen=pg.mkPen("#e05a3c", width=1.4), name="x")
        self.c_by = self.p_pos.plot(pen=pg.mkPen("#5ab4e0", width=1.4), name="y")
        self.p_pos.addLegend(offset=(-10, 10))
        self.p_pos.showGrid(x=True, y=True, alpha=0.25)

        self.p_tilt = pg.PlotWidget(title="tilt: commanded vs acknowledged (deg)")
        self.c_cx = self.p_tilt.plot(pen=pg.mkPen("#e05a3c", width=1.4))
        self.c_cy = self.p_tilt.plot(pen=pg.mkPen("#5ab4e0", width=1.4))
        self.c_ax = self.p_tilt.plot(pen=pg.mkPen("#e05a3c", width=1.0, style=Qt.DashLine))
        self.c_ay = self.p_tilt.plot(pen=pg.mkPen("#5ab4e0", width=1.0, style=Qt.DashLine))
        self.p_tilt.showGrid(x=True, y=True, alpha=0.25)

        self.p_rate = pg.PlotWidget(title="loop rate (Hz)")
        self.c_vhz = self.p_rate.plot(pen=pg.mkPen("#8fd18f", width=1.4))
        self.c_chz = self.p_rate.plot(pen=pg.mkPen("#d1b06f", width=1.4))
        self.p_rate.showGrid(x=True, y=True, alpha=0.25)

        for plot in (self.p_pos, self.p_tilt, self.p_rate):
            plot.setMinimumHeight(150)
            row.addWidget(plot)
        return panel

    # ==================================================================
    def _start_workers(self) -> None:
        self.camera.frame_ready.connect(self.video.update_frame)
        self.camera.detection.connect(self.control.on_detection, Qt.DirectConnection)
        self.camera.fps_measured.connect(self._on_camera_fps)
        self.camera.status.connect(self.statusBar().showMessage)

        self.control.tilt_command.connect(self._on_tilt)
        self.control.state_ready.connect(self._on_state)
        self.control.rate_measured.connect(self._on_control_rate)

        self.serial.telemetry.connect(self._on_telemetry)
        self.serial.line_received.connect(self._on_serial_line)
        self.serial.line_sent.connect(self._on_serial_sent)
        self.serial.pong.connect(self._on_pong)
        self.serial.connection_changed.connect(self._on_connection)

        self.camera.start()
        self.control.start()
        self.serial.start()
        self._refresh_ports()

        # Start with the buttons greyed until a link exists, then open the port
        # by itself if asked to. Opening a port commands no motion — the board
        # is not even reset by it — so this is safe, and it removes the one
        # step whose omission makes every button on the Machine tab look dead.
        self.machine_panel.set_link_state(False)
        if self.params.get("ser_autoconnect") and self.params.get("ser_port"):
            QTimer.singleShot(300, self._autoconnect)

    def _autoconnect(self) -> None:
        if self.serial.is_open:
            return
        port = self.params.get("ser_port")
        self.statusBar().showMessage("connecting to %s automatically..." % port, 3000)
        self.serial.connect_to(port, int(self.params.get("ser_baud")))

    # -- signal handlers -------------------------------------------------
    def _on_camera_fps(self, hz: float) -> None:
        self._vision_hz = hz

    def _on_control_rate(self, hz: float) -> None:
        self._control_hz = hz

    def _on_state(self, state) -> None:
        self._state = state

    def _on_tilt(self, x: float, y: float) -> None:
        """Runs on the control thread's signal, delivered on the GUI thread."""
        if self._estopped:
            return
        self._cmd = (x, y)
        self.video.set_tilt(x, y)
        if self._armed and self.serial.is_open:
            # The mode owns the height and the cadence; the loop owns the tilt.
            # A None means a move is still running and must not be interrupted.
            cmd = self.modes.command()
            if cmd is not None:
                tx, ty = (x, y) if cmd.allow_tilt else (0.0, 0.0)
                self.serial.send_pose(cmd.height_m, tx, ty, cmd.move_time)
                self._commanded_height = cmd.height_m

        s, t = self._state, self._telem
        self._buf["t"].append(time.monotonic() - self._t0)
        self._buf["bx"].append(s.x if s else float("nan"))
        self._buf["by"].append(s.y if s else float("nan"))
        self._buf["cx"].append(x)
        self._buf["cy"].append(y)
        self._buf["ax"].append(t.ack_x if t else float("nan"))
        self._buf["ay"].append(t.ack_y if t else float("nan"))

        if self.logger.active:
            self.logger.write([
                time.time(), time.monotonic(),
                s.x if s else "", s.y if s else "",
                s.radius if s else "", "",
                s.vx if s else "", s.vy if s else "",
                x, y,
                t.ack_x if t else "", t.ack_y if t else "",
                t.loop_hz if t else "", t.status if t else "",
                self.params.get("ctl_mode"),
                self.params.get("ctl_target_x"), self.params.get("ctl_target_y"),
            ])

    def _on_telemetry(self, telem) -> None:
        self._telem = telem
        self.txt_telem.append("ack %+.2f,%+.2f  mcu %.0f Hz  %s"
                              % (telem.ack_x, telem.ack_y, telem.loop_hz, telem.status))
        self._trim_telem()

    def _on_serial_line(self, line: str) -> None:
        self._log_serial("RX", line, "#5ab4e0")

    def _on_serial_sent(self, line: str) -> None:
        """Every outgoing line is shown.

        Without this the monitor stays empty however well the link works, because
        the firmware ships with VERBOSE_SERIAL_LOGGING off and answers nothing
        but PING. An empty monitor then looks like a dead link when it is really
        a silent one, which is the normal state.
        """
        self._log_serial("TX", line, "#e0a03c")

    def _on_pong(self, seconds: float) -> None:
        self._last_pong = time.monotonic()
        self._log_serial("--", "PONG after %.1f ms — board is alive"
                         % (seconds * 1000), "#8fd18f")

    def _log_serial(self, tag: str, line: str, colour: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.txt_telem.append(
            '<span style="color:#666">%s</span> '
            '<span style="color:%s;font-weight:bold">%s</span> '
            '<span style="color:%s">%s</span>'
            % (stamp, colour, tag, colour, _escape(line)))
        self._trim_telem()

    def _trim_telem(self) -> None:
        doc = self.txt_telem.document()
        if doc.blockCount() > 200:
            cursor = self.txt_telem.textCursor()
            cursor.movePosition(cursor.Start)
            cursor.movePosition(cursor.Down, cursor.KeepAnchor, doc.blockCount() - 200)
            cursor.removeSelectedText()

    def _on_connection(self, connected: bool, message: str) -> None:
        self.lbl_conn.setText("● " + message)
        self.lbl_conn.setStyleSheet(
            "color:%s;font-weight:bold;" % ("#3f8f5f" if connected else "#b3452c"))
        self.btn_connect.setText("Disconnect" if connected else "Connect")
        self.statusBar().showMessage(message, 4000)
        self.machine_panel.set_link_state(connected)
        self._log_serial("--", message, "#3f8f5f" if connected else "#b3452c")
        if connected:
            # Prove the link immediately rather than leaving the user to wonder
            # whether an empty monitor means broken or merely quiet.
            self._last_pong = None
            self.serial.send_ping()
            QTimer.singleShot(1500, self._check_pong)

    def _check_pong(self) -> None:
        if getattr(self, "_last_pong", None) is None:
            self._log_serial("!!", "no PONG within 1.5 s — the port is open but "
                                   "the board is not answering. Check that the "
                                   "sketch in Arduino/HighPrecisionStepperJuggler "
                                   "is the one flashed.", "#b3452c")

    def _send_raw_line(self) -> None:
        line = self.edit_raw.text().strip()
        if not line:
            return
        if not self.serial.is_open:
            self._log_serial("!!", "not connected", "#b3452c")
            return
        self.serial.send_raw(line)
        self.edit_raw.clear()

    def _on_video_clicked(self, x: float, y: float) -> None:
        self.params.set("ctl_target_x", x)
        self.params.set("ctl_target_y", y)

    # -- machine poses ------------------------------------------------------
    def _on_machine_message(self, text: str, ok: bool) -> None:
        """Repeat a Machine-tab message where it cannot be missed."""
        self.statusBar().showMessage(text, 0 if not ok else 5000)
        self._log_serial("--" if ok else "!!", text, "#8fd18f" if ok else "#b3452c")

    def _machine_blocked(self):
        """Why a manual move from the Machine tab would not survive, if so.

        An armed control loop commands a pose at the control rate, and the
        firmware clears its queued batches every time a line arrives, so a
        manual move sent underneath it is cancelled before it can finish.
        Saying that is far better than letting the button look dead.
        """
        if self._armed:
            return "the control loop is running and overrides manual moves — "                    "stop it on the Session tab first"
        return None

    def _origin_height(self) -> float:
        """Working origin, in metres above the plate's rest position.

        The plate at rest has no downward travel, so parking a little above it
        is what gives the control loop room to push either way.

        Every caller uses this as a height to send the plate to, so it also
        records it as the commanded height. That is what the readout checks the
        measured ball size against, and leaving it stale after a Go To Origin
        would make the check accuse a perfectly good detection.
        """
        self._commanded_height = self.params.get("mac_origin_offset") / 1000.0
        return self._commanded_height

    def _command_time(self) -> float:
        """One command period, floored by the firmware's own minimum.

        Each command supersedes the one before it, so asking for a longer move
        only adds lag between the tilt the controller chose and the tilt the
        plate is holding.
        """
        rate = max(1.0, float(self.params.get("ctl_rate_hz")))
        return max(machine.MOVE_DURATION_FLOOR, 1.0 / rate)

    def _go_origin(self) -> None:
        if self.serial.is_open:
            self.serial.send_pose(self._origin_height(), 0.0, 0.0,
                                  self.params.get("mac_move_time"))
            self.statusBar().showMessage("commanded to origin", 3000)
        else:
            self.statusBar().showMessage("not connected", 3000)

    # -- actions ----------------------------------------------------------
    def _refresh_ports(self) -> None:
        ports = available_ports()
        row = self.groups["Serial"].rows.get("ser_port")
        if row is not None:
            row.set_choices(tuple(ports) if ports else ("",))
        if ports and not self.params.get("ser_port"):
            self.params.set("ser_port", ports[0])
        self.statusBar().showMessage(
            "found %d serial port(s): %s" % (len(ports), ", ".join(ports) or "none"), 4000)

    def _toggle_serial(self) -> None:
        if self.serial.is_open:
            self.serial.disconnect_from()
        else:
            port = self.params.get("ser_port")
            if not port:
                QMessageBox.warning(self, "No port", "No serial port selected.")
                return
            self.serial.connect_to(port, int(self.params.get("ser_baud")))

    def _toggle_control(self, on: bool) -> None:
        if on and not self.serial.is_open:
            self.btn_run.setChecked(False)
            self._on_machine_message(
                "NOT CONNECTED — open the Serial tab and press Connect", False)
            return
        if on and self._estopped:
            self._estopped = False      # arming clears a previous stop
        self._armed = bool(on)
        self.control.set_enabled(on)
        self.btn_run.setText("Stop" if on else "Start")
        self.cmb_mode.setEnabled(not on)
        self.video.clear_trail()

        mode = self.params.get("mod_mode")
        if on:
            # Drop any lock earned while idle: it may be on a hand or on the
            # ceiling, and inheriting it would aim the loop at the wrong thing.
            self.camera.reset_tracking()
            self.modes.start(mode)
            self._on_machine_message("%s started" % mode, True)
        else:
            self.modes.stop()
            self.lbl_phase.setText("stopped")
            # Leaving the plate wherever the last phase put it would strand it
            # mid-stroke, so it is parked deliberately.
            if self.serial.is_open:
                self.serial.send_pose(self._origin_height(), 0.0, 0.0,
                                      self.params.get("mod_rise_time"))
            self._on_machine_message("%s stopped, returning to origin" % mode, True)

    def _emergency_stop(self) -> None:
        self._estopped = True
        self._armed = False
        self.modes.stop()
        self.lbl_phase.setText("EMERGENCY STOP")
        self.cmb_mode.setEnabled(True)
        self.control.set_enabled(False)
        self.btn_run.setChecked(False)
        self._cmd = (0.0, 0.0)
        self.video.set_tilt(0.0, 0.0)
        if self.serial.is_open:
            # There is no abort verb, so the safe state has to be commanded
            # rather than requested: level, at the working origin, in the
            # shortest move the firmware will accept.
            self.serial.send_pose(self._origin_height(), 0.0, 0.0,
                                  machine.MOVE_DURATION_FLOOR)
        self.statusBar().showMessage("EMERGENCY STOP — plate commanded level at origin", 0)

    def _save_preset(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save preset", "preset.json",
                                              "JSON (*.json)")
        if path:
            self.params.to_json(path)
            self._remember_preset(path)
            self.statusBar().showMessage("saved %s" % path, 4000)

    def _load_preset(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load preset", "", "JSON (*.json)")
        if path:
            self._apply_preset(path)

    def _load_recent_preset(self, index: int) -> None:
        path = self.cmb_presets.itemData(index)
        if path:
            self._apply_preset(path)

    def _apply_preset(self, path: str) -> None:
        try:
            self.params.from_json(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Preset", "Could not load:\n%s" % exc)
            return
        self._remember_preset(path)
        self.statusBar().showMessage("loaded %s" % path, 4000)

    def _remember_preset(self, path: str) -> None:
        if self.cmb_presets.findData(path) < 0:
            self.cmb_presets.insertItem(0, os.path.basename(path), path)
        self.cmb_presets.setCurrentIndex(max(0, self.cmb_presets.findData(path)))

    def _toggle_logging(self, on: bool) -> None:
        if on:
            path, _ = QFileDialog.getSaveFileName(self, "Log to CSV", "session.csv",
                                                  "CSV (*.csv)")
            if not path:
                self.btn_log.setChecked(False)
                return
            self.logger.start(path)
            self.btn_log.setText("Stop CSV logging")
        else:
            self.logger.stop()
            self.btn_log.setText("Start CSV logging…")
            self.lbl_log.setText("not recording")

    # -- periodic refresh --------------------------------------------------
    def _describe_mode(self) -> str:
        """What the selected mode will do, in numbers, before it is started."""
        origin = self.params.get("mac_origin_offset")
        if self.params.get("mod_mode") == BALANCE_JUGGLE:
            rise = self.params.get("mod_hop_rise")
            amp = self.params.get("mod_hop_mm") / 1000.0
            g = math.pi ** 2 * amp / (2.0 * rise * rise) / 9.81
            speed = math.pi * amp / (2.0 * rise)
            base = (self.params.get("mac_origin_offset")
                    + self.params.get("mod_balance_height")) / 1000.0
            top = base + amp
            reach = machine.arm_angles(top, 0.0, 0.0)[0]
            back = machine.forward_height(reach) - machine.HEIGHT_ORIGIN
            unreachable = abs(back - top) > 1e-6
            pulses = abs(machine.pulses_for(
                reach - machine.arm_angles(base, 0.0, 0.0)[0]))
            steps = math.pi * pulses / (2.0 * rise)
            warn = ""
            if unreachable:
                warn = (" The arms cannot reach %.0f mm, so this hop will be "
                        "silently clipped - lower the balancing height or the "
                        "hop." % (top * 1000))
            elif steps > 25000:
                warn = (" %.0f steps/s exceeds the firmware's 25000 ceiling; "
                        "make the rise slower." % steps)
            elif g < 1.0:
                warn = " Under 1 g, so the ball will not leave the plate."
            else:
                warn = " Tilt stays live throughout, including in the air."
            return ("Hold the ball at %.0f mm, and every %.1f s throw it %.0f mm "
                    "in %.2f s: %.2f g, leaving at %.2f m/s for a %.0f mm hop "
                    "with %.2f s of air.%s"
                    % (self.params.get("mod_balance_height"),
                       self.params.get("mod_hop_every"),
                       self.params.get("mod_hop_mm"), rise, g, speed,
                       1000.0 * speed * speed / (2 * 9.81),
                       2.0 * speed / 9.81, warn))
        if self.params.get("mod_mode") == BALANCE_REST:
            return ("Rise to %.0f mm, hold the ball lively for %.0f s, then "
                    "soften the gains over %.1f s (Kp %.3f->%.3f, window %d->%d) "
                    "so it slows and stops in the middle."
                    % (self.params.get("mod_balance_height"),
                       self.params.get("mod_hold_seconds"),
                       self.params.get("mod_rest_blend"),
                       self.params.get("pid_kp_x"), self.params.get("mod_rest_kp"),
                       self.params.get("ctl_vel_window"),
                       self.params.get("mod_rest_window")))
        if self.params.get("mod_mode") == BALANCING:
            return ("Rise to %.0f mm (%.0f mm above the plate's rest position) "
                    "over %.2f s, settle %.2f s, then hold and tilt every %.2f s."
                    % (self.params.get("mod_balance_height"),
                       origin + self.params.get("mod_balance_height"),
                       self.params.get("mod_rise_time"),
                       self.params.get("mod_settle_time"),
                       self.params.get("mod_balance_move_time")))
        low = self.params.get("mod_jug_low")
        high = self.params.get("mod_jug_high")
        base, top = origin + low, origin + high
        rise = self.params.get("mod_jug_rise_time")
        t = optics.throw(high - low, rise)
        win = optics.tight_window_mm(base)
        cycle = self.modes.cycle_time()

        if t is None:
            return ("Bounce %.0f to %.0f mm, but the rise peaks at only %.2f g "
                    "- the ball never leaves the plate. Shorten the rise or "
                    "lengthen the stroke."
                    % (low, high, self.modes.separation_g()))

        # The plate has to be waiting where the ball comes down. Too short a
        # dwell and it is already falling away; too long and the ball sits
        # there being steered by nothing.
        dwell = self.params.get("mod_jug_top_dwell")
        note = ""
        if dwell < t["hang_time"] - 0.02:
            note = (" Top dwell %.2f s is short of the %.2f s the ball is in "
                    "the air, so the plate drops away before the catch."
                    % (dwell, t["hang_time"]))
        elif dwell > t["hang_time"] + 0.05:
            note = (" Top dwell %.2f s outlasts the %.2f s hop, so the ball "
                    "waits on a plate that is not steering it."
                    % (dwell, t["hang_time"]))

        steps = math.pi * abs(machine.pulses_for(
            machine.arm_angles(top / 1000.0, 0.0, 0.0)[0]
            - machine.arm_angles(base / 1000.0, 0.0, 0.0)[0])) / (2.0 * rise)
        if steps > 25000:
            note += (" %.0f steps/s is over the firmware's 25000 ceiling, so "
                     "the stroke will not be delivered." % steps)

        return ("Bounce %.0f to %.0f mm: %.2f g throws the ball off %.0f mm up "
                "the stroke at %.2f m/s, for a hop %.0f mm clear of the plate "
                "with %.2f s of air. Cycle %.2f s (%.1f Hz). The camera sees "
                "+-%.0f mm of plate at the bottom and +-%.0f mm at the catch, "
                "and the ball spans %.0f px there.%s"
                % (low, high, t["peak_g"], t["release_mm"], t["exit_speed"],
                   t["clearance_mm"], t["hang_time"], cycle,
                   1.0 / max(1e-6, cycle), win,
                   optics.tight_window_mm(top), optics.ball_radius_px(top),
                   note))

    def _refresh_readouts(self) -> None:
        self.lbl_mode.setText(self._describe_mode())
        if self.modes.running:
            phase = self.modes.phase
            if self.params.get("mod_mode") == JUGGLING and self.modes.cycles:
                phase += "   cycle %d" % self.modes.cycles
            elif self.params.get("mod_mode") == BALANCE_JUGGLE and self.modes.hops:
                phase += "   hop %d" % self.modes.hops
            self.lbl_phase.setText(phase)
        s = self._state
        self.video.set_target(self.params.get("ctl_target_x"),
                              self.params.get("ctl_target_y"))
        lines = [
            "ball      %s" % ("%+7.1f, %+7.1f px   r=%.1f" % (s.x, s.y, s.radius)
                              if s else "not detected"),
            "velocity  %s" % ("%+7.1f, %+7.1f px/s" % (s.vx, s.vy) if s else "—"),
            "command   %+6.2f, %+6.2f deg" % self._cmd,
            "vision    %.1f Hz" % getattr(self, "_vision_hz", 0.0),
            "control   %.1f Hz" % getattr(self, "_control_hz", 0.0),
            "serial    %s" % ("open" if self.serial.is_open else "closed"),
        ]
        if s is not None:
            # Detection RATE is a useless health metric on its own: this rig
            # has twice reported a confident ball at badly wrong size, once by
            # locking onto a halo and once by seeing only the bright core of an
            # under-exposed ball. Both looked perfect here. The ball is a known
            # size at a known distance, so the radius can simply be checked
            # against the height the plate was last sent to.
            want = optics.ball_radius_px(1000.0 * self._commanded_height)
            err = 100.0 * (s.radius / want - 1.0)
            note = ""
            if abs(err) > 15.0:
                note = ("   <-- %s: check exposure and clipping"
                        % ("only part of the ball" if err < 0 else "bigger than the ball"))
            lines.append("radius    %.1f px, expected %.1f at %.0f mm (%+.0f%%)%s"
                         % (s.radius, want, 1000.0 * self._commanded_height, err, note))
        else:
            # "not detected" is the least useful thing a detector can say, so
            # say which gate turned the blob down instead.
            for note in self.camera._vision.rejections[:3]:
                lines.append("  rejected: %s" % note)
        if self._estopped:
            lines.append("\n*** EMERGENCY STOP ACTIVE ***")
        self.lbl_readout.setText("\n".join(lines))

        if self.logger.active:
            self.lbl_log.setText("recording %d rows → %s"
                                 % (self.logger.row_count,
                                    os.path.basename(self.logger.path or "")))

    def _refresh_plots(self) -> None:
        t = list(self._buf["t"])
        if not t:
            return
        self.c_bx.setData(t, list(self._buf["bx"]))
        self.c_by.setData(t, list(self._buf["by"]))
        self.c_cx.setData(t, list(self._buf["cx"]))
        self.c_cy.setData(t, list(self._buf["cy"]))
        self.c_ax.setData(t, list(self._buf["ax"]))
        self.c_ay.setData(t, list(self._buf["ay"]))
        self._buf["vhz"].append(getattr(self, "_vision_hz", 0.0))
        self._buf["chz"].append(getattr(self, "_control_hz", 0.0))
        n = min(len(t), len(self._buf["vhz"]))
        if n:
            self.c_vhz.setData(t[-n:], list(self._buf["vhz"])[-n:])
            self.c_chz.setData(t[-n:], list(self._buf["chz"])[-n:])

    # ==================================================================
    def closeEvent(self, event) -> None:
        """Level the plate before letting the process exit."""
        try:
            self.control.set_enabled(False)
            if self.serial.is_open:
                self.serial.send_pose(self._origin_height(), 0.0, 0.0, 0.5)
                time.sleep(0.25)        # give the writer thread a tick to drain
            self.logger.stop()
            self.control.stop()
            self.camera.stop()
            self.serial.stop()
        finally:
            event.accept()
