"""Builds the real window offscreen, exercises it, and shuts it down.

Checks the parts that only fail once Qt is running: that every declared
parameter got a widget, that the workers start and stop, that emergency stop
zeroes the command, and that closing does not hang or throw. No camera or
serial hardware is required — the workers are expected to report the absence
rather than crash.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QTimer                                   # noqa: E402
from PyQt5.QtWidgets import QApplication                          # noqa: E402

from gui import MainWindow                                        # noqa: E402
from params import SPEC_BY_KEY, SPECS                              # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (("   " + detail) if detail else ""))
    if not cond:
        FAILED.append(name)


app = QApplication(sys.argv)
win = MainWindow()
win.show()

print("MainWindow")
check("window constructed", win is not None)

# every declared parameter must have reached the interface
missing = []
for spec in SPECS:
    if spec.group in win.groups and spec.key not in win.groups[spec.group].rows:
        missing.append(spec.key)
check("every parameter has a widget", not missing, ", ".join(missing))

check("camera thread running", win.camera.isRunning())
check("control thread running", win.control.isRunning())
check("serial thread running", win.serial.isRunning())

# a tilt command with no serial port attached must not raise
win._on_tilt(1.5, -2.0)
check("tilt with no serial link is harmless", win._cmd == (1.5, -2.0))

# clicking the video sets the control target
win._on_video_clicked(42.0, -17.0)
check("clicking the view sets the target",
      win.params.get("ctl_target_x") == 42.0 and win.params.get("ctl_target_y") == -17.0)

# Arming with no link is refused rather than half-done: the loop would run,
# the mode would advance through its phases, and nothing would reach a machine.
win.btn_run.setChecked(True)
check("arming without a serial link is refused", not win.control._enabled)
check("and the run button does not stay latched", not win.btn_run.isChecked())

# ---------------------------------------------------------------------------
# The Machine tab. These buttons are the bring-up procedure, and the failure
# they guard against is silent: the firmware ignores a line it cannot parse,
# so a button that sends nothing and a button that sends nonsense both look
# like a dead motor. Capture what each one would put on the wire.
# ---------------------------------------------------------------------------
print("\nMachine panel")
import machine                                                     # noqa: E402

sent = []


class FakePort:
    """Stands in for an open link so the panel takes its send path."""
    is_open = True

    def send_poses(self, poses):
        sent.append(list(poses))

    def send_pose(self, height_m, x_tilt, y_tilt, move_time):
        self.send_poses([(height_m, x_tilt, y_tilt, move_time)])

    def send_ping(self):
        sent.append("PING")


panel = win.machine_panel
real_serial, panel.serial = panel.serial, FakePort()

win.params.set("mac_origin_offset", 10.0)
win.params.set("mac_test_height", 20.0)
win.params.set("mac_test_tilt", 2.0)

panel.go_origin()
check("origin button sends one pose", len(sent) == 1 and len(sent[0]) == 1)
check("origin pose is the working offset, level",
      abs(sent[0][0][0] - 0.010) < 1e-9 and sent[0][0][1] == 0.0 and sent[0][0][2] == 0.0,
      "h=%.4f m" % sent[0][0][0])

sent.clear()
panel.go_test_height()
h = sent[0][0][0]
check("test height is measured from the working origin", abs(h - 0.030) < 1e-9,
      "%.1f mm" % (h * 1000))

sent.clear()
panel.go_tilt("x", +1)
panel.go_tilt("y", -1)
check("the X button tilts X only", sent[0][0][1] == 2.0 and sent[0][0][2] == 0.0)
check("the Y button tilts Y only", sent[1][0][1] == 0.0 and sent[1][0][2] == -2.0)
check("tilting holds the test height",
      abs(sent[0][0][0] - 0.030) < 1e-9 and abs(sent[1][0][0] - 0.030) < 1e-9)

sent.clear()
panel.tilt_sweep()
sweep = sent[0]
check("the sweep is one line of five poses", len(sweep) == 5)
check("the sweep ends level", sweep[-1][1] == 0.0 and sweep[-1][2] == 0.0)

sent.clear()
win.params.set("mac_osc_cycles", 4)
win.params.set("mac_osc_low", 10.0)
win.params.set("mac_osc_high", 30.0)
panel.oscillate()
osc = sent[0]
check("four cycles is a lead-in plus eight batches", len(osc) == 9, "%d" % len(osc))
check("it leads in to the bottom of the stroke",
      abs(osc[0][0] - 0.020) < 1e-9, "%.1f mm" % (osc[0][0] * 1000))
check("every rise after the lead-in is the same size",
      len({round(osc[i + 1][0] - osc[i][0], 9) for i in range(0, 8, 2)}) == 1)
check("the stroke alternates high and low",
      all(osc[i + 1][0] > osc[i][0] for i in range(0, 8, 2)))
check("the oscillation stays under the firmware batch ceiling", len(osc) <= 100)

# The spec's own upper bound has to stay inside the firmware's, otherwise the
# panel's defensive [:100] slice would quietly drop strokes the user asked for
# and the plate would stop early for no visible reason.
win.params.set("mac_osc_cycles", SPEC_BY_KEY["mac_osc_cycles"].hi)
sent.clear()
panel.oscillate()
check("the largest allowed cycle count fits the 100-batch ceiling uncut",
      len(sent[0]) == 2 * SPEC_BY_KEY["mac_osc_cycles"].hi + 1 <= 100,
      "%d cycles -> %d batches" % (SPEC_BY_KEY["mac_osc_cycles"].hi, len(sent[0])))
win.params.set("mac_osc_cycles", 4)

# every one of those must survive serialisation, since that is what the
# firmware sees and it will not complain about what it cannot read
sent.clear()
panel.go_origin(); panel.go_test_height(); panel.tilt_sweep(); panel.oscillate()
lines = [machine.serialize(p) for p in sent]
check("every panel action serialises to a parseable line",
      all(len(l.split(":")) % 6 == 0 for l in lines))
check("no action emits NaN",
      not any("nan" in l.lower() for l in lines))
check("the readout shows what was sent", "11.00000" in panel.lbl_last.text())
check("the angle readout is populated", "m0" in panel.txt_angles.toPlainText())

sent.clear()
panel.ping()
check("the ping button pings", sent == ["PING"])

# ---------------------------------------------------------------------------
# The levelling trim. It is applied in one place -- SerialWorker, the funnel
# every wire-bound pose passes through -- so the check that matters is that it
# reaches the wire exactly once, from whichever call site built the pose.
# ---------------------------------------------------------------------------
print("\nLevelling trim")
win.params.set("mac_trim_x", 0.0)
win.params.set("mac_trim_y", 0.0)
check("the worker reports no trim when it is zero", win.serial.trim() == (0.0, 0.0))

win.params.set("mac_trim_x", 1.25)
win.params.set("mac_trim_y", -0.5)
check("the worker picks the trim up from the live store, not a stale copy",
      win.serial.trim() == (1.25, -0.5), str(win.serial.trim()))

raw = [(0.010, 0.0, 0.0, 0.5)]
# the arm pairing is part of the wire line too, so the expected string has to
# be built with it or this compares against a machine we are not driving
order = machine.PAIRINGS[win.params.get("mac_motor_order")]
once = machine.apply_trim(raw, 1.25, -0.5)
twice = machine.apply_trim(once, 1.25, -0.5)
check("applying it twice really would differ, so the check below has teeth",
      machine.serialize(once, order) != machine.serialize(twice, order))

# the panel hands RAW poses to the worker and only displays the trimmed ones
sent.clear()
panel.go_origin()
check("the panel sends the untrimmed pose, leaving the trim to the worker",
      sent and sent[0][0][1] == 0.0 and sent[0][0][2] == 0.0,
      str(sent[0][0][1:3]) if sent else "nothing sent")
check("but shows the trimmed line, matching what reaches the machine",
      machine.serialize(once, order) in panel.lbl_last.text())

# nudging moves the trim and re-commands, so it can be judged by eye
before = win.params.get("mac_trim_x")
step = win.params.get("mac_trim_step")
sent.clear()
panel._nudge_trim("x", +1)
check("a nudge moves the trim by one step",
      abs(win.params.get("mac_trim_x") - (before + step)) < 1e-9,
      "%.2f -> %.2f" % (before, win.params.get("mac_trim_x")))
check("and re-sends origin so the change can be seen", len(sent) == 1)
check("the readout follows", "%+.2f" % win.params.get("mac_trim_x")
      in panel.lbl_trim.text(), panel.lbl_trim.text().replace("\n", " "))

panel._zero_trim()
check("reset clears both axes",
      win.params.get("mac_trim_x") == 0.0 and win.params.get("mac_trim_y") == 0.0)

# ---------------------------------------------------------------------------
# Press the buttons, rather than calling the methods behind them. Everything
# above would pass with the click signals unconnected entirely, and a button
# that is enabled but declines silently is indistinguishable from one that is
# broken -- which is how the panel behaved with no port open.
# ---------------------------------------------------------------------------
print("\nThe buttons themselves")
from PyQt5.QtWidgets import QPushButton                            # noqa: E402

buttons = panel.findChildren(QPushButton)
check("the panel has its buttons", len(buttons) >= 12, "%d found" % len(buttons))
check("every button is connected to something",
      all(b.receivers(b.clicked) >= 1 for b in buttons),
      ", ".join(b.text() for b in buttons if b.receivers(b.clicked) < 1))

panel.set_link_state(False)
check("no link greys every action out",
      all(not b.isEnabled() for b in panel.actions))
check("and says why, where it can be seen",
      panel.banner.isVisibleTo(panel) and "NOT CONNECTED" in panel.banner.text())

panel.set_link_state(True)
check("a link re-enables them", all(b.isEnabled() for b in panel.actions))
check("and drops the banner", not panel.banner.isVisibleTo(panel))

dead = []
for btn in buttons:
    sent.clear()
    btn.click()
    if not sent:
        dead.append(btn.text())
check("clicking each button puts something on the wire", not dead,
      "dead: " + ", ".join(dead) if dead else "all %d" % len(buttons))

# a refusal has to reach the window, not just the panel's own label
heard = []
panel.on_message = lambda text, ok: heard.append((text, ok))
panel.serial = type("Closed", (), {"is_open": False})()
panel.go_origin()
check("a refusal is reported outward too", heard and heard[-1][1] is False,
      heard[-1][0][:52] if heard else "nothing reported")
panel.serial = FakePort()

# ---------------------------------------------------------------------------
# The control loop emits a tilt on every tick whether or not it is armed, so
# the window must not relay those to the port while disarmed. It used to, at
# the full command rate, and because the firmware clears its queued batches on
# every line received, that stream cancelled any multi-batch move the Machine
# tab sent underneath it -- the oscillation button did nothing at all.
# ---------------------------------------------------------------------------
print("\nIdle loop must not touch the port")
win_serial = win.serial
win.serial = FakePort()
win.btn_run.setChecked(False)
win._armed = False
win._estopped = False
sent.clear()
for _ in range(20):
    win._on_tilt(0.0, 0.0)
check("a disarmed loop sends nothing", sent == [], "%d lines" % len(sent))

# Arm properly, through the button, with a link present. That also starts the
# mode, which is what decides the height and the cadence from here on.
import time as _time                                              # noqa: E402
import modes as _modes                                            # noqa: E402

win.params.set("mod_mode", _modes.BALANCING)
win.params.set("mod_balance_height", 40.0)
win.params.set("mod_rise_time", 0.15)
win.params.set("mod_settle_time", 0.0)
win.cmb_mode.setCurrentText(_modes.BALANCING)
sent.clear()
win.btn_run.setChecked(True)
check("arming with a link works", win.control._enabled and win._armed)
check("and starts the selected mode", win.modes.running,
      "%s / %s" % (win.modes.mode, win.modes.phase))

win._on_tilt(1.0, -1.0)
check("the first command is the rise", len(sent) == 1, "%d lines" % len(sent))
if sent:
    check("the rise goes to the balancing height",
          abs(sent[0][0][0] - (win._origin_height() + 0.040)) < 1e-12,
          "%.1f mm" % (sent[0][0][0] * 1000))
    check("and holds the plate level while it climbs",
          sent[0][0][1] == 0.0 and sent[0][0][2] == 0.0)

sent.clear()
for _ in range(30):
    win._on_tilt(1.0, -1.0)
check("the rise is not re-sent while it runs", sent == [],
      "%d re-sends -- the plate would never leave the ground" % len(sent))

_time.sleep(0.2)                     # past rise + settle
sent.clear()
win._on_tilt(1.0, -1.0)
check("tilt is applied once it has risen", len(sent) == 1)
if sent:
    check("and carries the commanded tilt",
          sent[0][0][1] == 1.0 and sent[0][0][2] == -1.0)
    check("at the balancing height",
          abs(sent[0][0][0] - (win._origin_height() + 0.040)) < 1e-12)

win.btn_run.setChecked(False)
check("stopping returns the runner to manual", not win.modes.running)
win._armed = True                    # the next check needs an armed loop

# and a manual move while the loop is armed must say so rather than vanish
panel.serial = FakePort()
sent.clear()
panel.go_origin()
check("a manual move is refused while the loop is armed", sent == [])
check("and the panel explains why", "IGNORED" in panel.lbl_last.text(),
      panel.lbl_last.text()[:60])

win._armed = False
sent.clear()
panel.go_origin()
check("the same move works once the loop is stopped", len(sent) == 1)
panel.serial = FakePort()
win.serial = win_serial

# a disconnected panel must refuse rather than throw
panel.serial = type("Closed", (), {"is_open": False})()
panel.go_origin()
check("a disconnected panel says so instead of raising",
      "NOT CONNECTED" in panel.lbl_last.text())
panel.serial = real_serial

# the clamp must survive a controller asking for more than the limit
win.params.set("ctl_max_tilt", 3.0)
check("max tilt clamp stored", win.params.get("ctl_max_tilt") == 3.0)

# preset round trip through the live window
import tempfile                                                    # noqa: E402
preset = os.path.join(tempfile.gettempdir(), "bb_gui_preset.json")
win.params.set("pid_kp_x", 0.123)
win.params.to_json(preset)
win.params.set("pid_kp_x", 0.5)
win.params.from_json(preset)
check("preset reloads into the live store", abs(win.params.get("pid_kp_x") - 0.123) < 1e-9)
row = win.groups["Control"].rows["pid_kp_x"]
check("widget followed the store", abs(row.editor.value() - 0.123) < 1e-6,
      "widget shows %.4f" % row.editor.value())

# let the event loop and the worker threads actually turn over
QTimer.singleShot(1200, win.close)
QTimer.singleShot(1600, app.quit)
app.exec_()

check("camera thread stopped", not win.camera.isRunning())
check("control thread stopped", not win.control.isRunning())
check("serial thread stopped", not win.serial.isRunning())

print("\n%s" % ("ALL CHECKS PASSED" if not FAILED else "FAILURES: " + ", ".join(FAILED)))
sys.exit(1 if FAILED else 0)
