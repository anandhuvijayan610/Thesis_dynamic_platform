"""Put the plate back on the calibrated level origin.

The motors hold whatever pose they were last given, so anything that stops
without tidying up — a script that ends mid-sequence, a window that is killed
rather than closed — leaves the plate leaning at the last tilt the control loop
asked for. That looks exactly like the levelling trim having drifted, and it is
not: it is a plate that was never told to go home.

    python park.py

Nothing else may hold the port while this runs.
"""
from __future__ import annotations

import sys
import time

from PyQt5.QtWidgets import QApplication

import machine
from gui import MainWindow

app = QApplication(sys.argv)
win = MainWindow()
win.show()

sent = []
win.serial.line_sent.connect(sent.append)


def wait(seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.004)


wait(3.5)
if not win.serial.is_open:
    print("no serial link — close the GUI first, then run this again")
    sys.exit(1)

trim = (win.params.get("mac_trim_x"), win.params.get("mac_trim_y"))
print("trim   X %+.2f  Y %+.2f      pairing %s"
      % (trim[0], trim[1], win.params.get("mac_motor_order")))

sent.clear()
win.machine_panel.go_origin()
wait(1.6)

for line in sent:
    print("sent   %s" % line)

# What the same pose would look like with no trim at all, so it is obvious at a
# glance whether the correction actually went out: untrimmed, all four arms
# carry the identical angle.
plain = machine.serialize([(win.params.get("mac_origin_offset") / 1000.0, 0.0, 0.0, 0.5)],
                          machine.PAIRINGS[win.params.get("mac_motor_order")])
print("untrimmed it would be:")
print("       %s" % plain)
print()
print("The plate is now on the calibrated origin. If a level says otherwise,")
print("the arms have moved and the trim needs setting again on the Machine tab.")

wait(0.6)
win.close()
wait(0.8)
