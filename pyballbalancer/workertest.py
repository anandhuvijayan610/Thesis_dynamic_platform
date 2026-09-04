"""Drives the real SerialWorker against the real board.

hwtest.py proves the link with a bare pyserial port. This proves the class the
GUI actually uses, over the same wire, so a discrepancy between the two points
at the worker rather than the hardware.

    python workertest.py           probe only
    python workertest.py --move    probe, then move the plate
"""
from __future__ import annotations

import sys
import time

from PyQt5.QtCore import QCoreApplication, QTimer

import machine
from serial_io import SerialWorker, available_ports

MOVE = "--move" in sys.argv
PORT = next((a for a in sys.argv[1:] if a.upper().startswith("COM")), None)

app = QCoreApplication(sys.argv)
worker = SerialWorker()

rx, tx, conn, pongs = [], [], [], []
worker.line_received.connect(lambda s: (rx.append(s), print("   RX  %s" % s)))
worker.line_sent.connect(lambda s: (tx.append(s), print("   TX  %s" % s)))
worker.connection_changed.connect(
    lambda ok, msg: (conn.append((ok, msg)), print("   ..  %s" % msg)))
worker.pong.connect(lambda dt: (pongs.append(dt),
                                print("   ..  PONG after %.1f ms" % (dt * 1000))))


def wait(seconds: float) -> None:
    """Spin the event loop so queued signals are actually delivered."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


ports = available_ports()
print("ports: %s" % (", ".join(ports) or "NONE"))
if not ports:
    sys.exit("no serial ports")
port = PORT or ports[0]

worker.start()
print("\n1. connect to %s" % port)
worker.connect_to(port, 921600)
wait(1.5)
if not worker.is_open:
    print("\nFAILED to open the port. If this says 'access is denied' while")
    print("hwtest.py works, something opened the port in between -- most likely")
    print("a copy of the GUI still running.")
    worker.stop()
    sys.exit(1)
print("   port is open")

print("\n2. PING through the worker")
worker.send_ping()
wait(1.5)

print("\n3. a bad marker, to force a reply out of the firmware")
worker._pending_raw.append("99.00000:0:0:0:0:0.5")
wait(1.2)

if MOVE:
    print("\n4. move: origin -> +10 mm -> origin, 1 s each")
    for label, pose in (("origin", (0.0, 0.0, 0.0, 1.0)),
                        ("+10 mm", (0.010, 0.0, 0.0, 1.0)),
                        ("origin", (0.0, 0.0, 0.0, 1.0))):
        print("   %s" % label)
        worker.send_pose(*pose)
        wait(1.6)

    print("\n5. tilt +2 deg then level, at 20 mm")
    worker.send_poses([(0.020, 2.0, 0.0, 0.8), (0.020, 0.0, 0.0, 0.8)])
    wait(2.4)
else:
    print("\n4. movement skipped -- pass --move to run it")

worker.stop()
wait(0.3)

print("\n" + "=" * 60)
print("connection events : %d" % len(conn))
print("lines sent        : %d" % len(tx))
print("lines received    : %d" % len(rx))
print("pongs             : %d" % len(pongs))
ok = worker_ok = bool(pongs) and bool(tx)
print("\n%s" % ("WORKER OK -- it sends and it receives"
                if ok else "WORKER FAULT -- see the log above"))
print("=" * 60)
sys.exit(0 if ok else 1)
