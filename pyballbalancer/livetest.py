"""The oscillation, tested with the whole GUI alive around it.

movetest.py builds only the Machine panel, which is why it never caught the
bug this file exists for: the control loop ticks and emits a tilt on every
tick whether or not it is armed, and the window used to relay all of those to
the port. At the command rate that stream cancelled any multi-batch move sent
underneath it, because the firmware clears its queued batches every time a
line arrives. The button looked dead while the link was perfect.

So this builds the real MainWindow, with the camera and control threads
running, and checks what actually reaches the port.

    python livetest.py          on real hardware, via COM3

Close the GUI first — Windows lets one program own the port.
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication                          # noqa: E402

from gui import MainWindow                                        # noqa: E402
from serial_io import available_ports                             # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", name,
                          ("   " + detail) if detail else ""))
    if not cond:
        FAILED.append(name)


app = QApplication(sys.argv)
win = MainWindow()
win.show()

sent = []
win.serial.line_sent.connect(sent.append)
win.serial.line_received.connect(lambda s: print("      RX  %s" % s))


def wait(seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


ports = available_ports()
if not ports:
    print("no serial ports — is the Teensy plugged in?")
    sys.exit(1)
port = ports[0]

print("Full window is up: camera, control loop and serial threads all running.")
print("Connecting to %s\n" % port)
win.params.set("ser_port", port)
win._toggle_serial()
wait(2.5)

if not win.serial.is_open:
    print("could not open %s — is the GUI still running?" % port)
    sys.exit(1)

print("Idle, disarmed")
sent.clear()
wait(3.0)
chatter = [s for s in sent if s != "PING"]
check("three idle seconds put nothing on the wire", not chatter,
      "%d lines — the idle loop is still flooding the port" % len(chatter))

print("\nUp / down cycle, with the control loop running but disarmed")
sent.clear()
win.machine_panel.oscillate()
wait(0.4)
osc = [s for s in sent if s.startswith("11.")]
check("the oscillation line went out", len(osc) == 1, "%d lines" % len(osc))
if osc:
    batches = len(osc[0].split(":")) // 6
    check("it is the whole batch, not a single pose", batches == 9,
          "%d batches" % batches)
    print("      TX  %s..." % osc[0][:96])

run = 2 * int(win.params.get("mac_osc_cycles")) * (win.params.get("mac_osc_time") + 0.05)
print("      running for %.1f s — watch the plate" % run)
sent.clear()
wait(run + 1.0)
check("nothing interrupted it while it ran", not sent,
      "%d lines cut in: %s" % (len(sent), sent[:2]))

print("\nBack to origin")
sent.clear()
win.machine_panel.go_origin()
wait(0.4)
check("the origin command went out", len(sent) == 1)
if sent:
    print("      TX  %s" % sent[0])
wait(1.2)

win.close()
wait(1.2)
app.quit()

print("\n" + "=" * 62)
print("%s" % ("ALL CHECKS PASSED — the oscillation now survives the live GUI"
              if not FAILED else "FAILURES: " + ", ".join(FAILED)))
print("=" * 62)
sys.exit(1 if FAILED else 0)
