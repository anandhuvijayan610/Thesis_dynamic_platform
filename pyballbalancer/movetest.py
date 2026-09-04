"""Presses the Machine tab's buttons for real, on real hardware.

Not a re-implementation of what the buttons do — it builds the actual
MachinePanel and calls the same methods the clicks call, through the same
SerialWorker, so a pass here means the GUI path works and not merely that some
equivalent code does.

    python movetest.py            origin, then up/down, then back to origin
    python movetest.py --tilt     also sweep the two tilt axes

Close the GUI first: Windows lets one program own COM3.
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication                          # noqa: E402

import machine                                                    # noqa: E402
from machine_panel import MachinePanel                            # noqa: E402
from params import ParameterStore                                 # noqa: E402
from serial_io import SerialWorker, available_ports               # noqa: E402
from widgets import ParamGroup                                    # noqa: E402

TILT = "--tilt" in sys.argv
PORT = next((a for a in sys.argv[1:] if a.upper().startswith("COM")), None)

app = QApplication(sys.argv)
params = ParameterStore()
worker = SerialWorker()

sent, received, pongs = [], [], []
worker.line_sent.connect(lambda s: sent.append(s))
worker.line_received.connect(lambda s: (received.append(s), print("      RX  %s" % s)))
worker.pong.connect(lambda dt: pongs.append(dt))
worker.connection_changed.connect(lambda ok, m: print("   ..  %s" % m))


def wait(seconds: float) -> None:
    """Turn the event loop, so queued signals are actually delivered."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def show_last() -> None:
    if sent:
        print("      TX  %s" % sent[-1])


ports = available_ports()
if not ports:
    sys.exit("no serial ports — is the Teensy plugged in?")
port = PORT or ports[0]

worker.start()
print("Connecting to %s" % port)
worker.connect_to(port, 921600)
wait(1.5)
if not worker.is_open:
    print("\nCould not open %s. If the GUI is still running it owns the port." % port)
    worker.stop()
    sys.exit(1)

worker.send_ping()
wait(1.0)
print("   PING answered: %s" % ("yes, %.0f ms" % (pongs[0] * 1000) if pongs else "NO"))

panel = MachinePanel(params, worker, ParamGroup("Machine", params))

origin = params.get("mac_origin_offset")
lo = params.get("mac_osc_low")
hi = params.get("mac_osc_high")
stroke = params.get("mac_osc_time")
cycles = int(params.get("mac_osc_cycles"))

print("\nSettings in use")
print("   working origin   %.0f mm above the plate's rest position" % origin)
print("   oscillation      %.0f -> %.0f mm above the origin (%.0f -> %.0f mm absolute)"
      % (lo, hi, origin + lo, origin + hi))
print("   stroke           %.2f s   cycles %d" % (stroke, cycles))
rise = (hi - lo) / 1000.0
peak = 3.14159265 ** 2 * rise / (2.0 * stroke ** 2)
print("   peak acceleration %.2f m/s^2 = %.2f g  (the ball stays in contact below 1 g)"
      % (peak, peak / 9.81))

# ---------------------------------------------------------------- go to origin
print("\n1. GO TO ORIGIN")
panel.go_origin()
wait(0.3)
show_last()
wait(params.get("mac_move_time") + 0.6)
print("      plate should now be level, %.0f mm above its rest position" % origin)

# ------------------------------------------------------------------ up and down
print("\n2. UP AND DOWN  (%d cycles, about %.1f s)" % (cycles, 2 * cycles * stroke))
panel.oscillate()
wait(0.3)
show_last()
run_time = 2 * cycles * (stroke + 0.05) + 1.0
print("      running...")
wait(run_time)
print("      done — the plate should have risen and fallen %d times" % cycles)

# ------------------------------------------------------------------------ tilt
if TILT:
    print("\n3. TILT SWEEP  (+X, -X, +Y, -Y, level) at %.0f mm"
          % params.get("mac_test_height"))
    panel.tilt_sweep()
    wait(0.3)
    show_last()
    wait(5 * (params.get("mac_move_time") + 0.05) + 1.0)
    print("      done")

# -------------------------------------------------------------- back to origin
print("\n%d. BACK TO ORIGIN" % (4 if TILT else 3))
panel.go_origin()
wait(0.3)
show_last()
wait(params.get("mac_move_time") + 0.8)

worker.stop()
wait(0.3)

print("\n" + "=" * 64)
print("lines sent      : %d" % len(sent))
print("lines received  : %d   (silence is normal — the firmware only answers PING)"
      % len(received))
print("PONG            : %s" % ("yes" if pongs else "NO"))

bad = [s for s in sent if s != "PING" and len(s.split(":")) % 6]
complaints = [r for r in received if "did NOT match" in r]

ok = bool(pongs) and not bad and not complaints and len(sent) >= 4
if bad:
    print("\nMALFORMED LINES SENT:")
    for b in bad:
        print("   %s" % b)
if complaints:
    print("\nTHE FIRMWARE REJECTED A BATCH:")
    for c in complaints:
        print("   %s" % c)

print("\n%s" % ("EVERY COMMAND WENT OUT CLEAN AND THE BOARD IS ANSWERING.\n"
                "If the plate did not physically move, the fault is past the\n"
                "microcontroller: driver enable, motor power, or DM542T wiring."
                if ok else "SOMETHING IS WRONG — see above."))
print("=" * 64)
sys.exit(0 if ok else 1)
