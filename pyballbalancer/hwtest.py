"""Direct hardware probe. No GUI, no threads, no Qt.

The firmware ships with VERBOSE_SERIAL_LOGGING set to 0, so it answers PING
and says nothing else at all. That silence is normal, and it means a working
link and a dead link look identical from the outside. This script is the way
to tell them apart: it opens the port itself, sends known-good lines, and
reports every byte that comes back.

    python hwtest.py            probe only, no movement
    python hwtest.py --move     probe, then move the plate

Nothing else may hold the port while this runs -- not the GUI, not the Arduino
Serial Monitor. Windows allows exactly one owner.
"""
from __future__ import annotations

import sys
import time

import serial
from serial.tools import list_ports

import machine

BAUD = 921600           # firmware: Serial.begin(921600)


def drain(port: serial.Serial, seconds: float, label: str) -> bytes:
    """Collect everything the board says for a while."""
    end = time.monotonic() + seconds
    got = b""
    while time.monotonic() < end:
        waiting = port.in_waiting
        if waiting:
            got += port.read(waiting)
        else:
            time.sleep(0.005)
    if got:
        for line in got.decode("ascii", "replace").splitlines():
            if line.strip():
                print("      RX  %s" % line.strip())
    else:
        print("      RX  (nothing) %s" % label)
    return got


def send(port: serial.Serial, line: str) -> None:
    payload = (line + "\n").encode("ascii")
    print("      TX  %s" % line)
    written = port.write(payload)
    port.flush()
    if written != len(payload):
        print("      !!  only %d of %d bytes written" % (written, len(payload)))


def main() -> int:
    move = "--move" in sys.argv

    ports = list(list_ports.comports())
    print("Serial ports")
    for p in ports:
        print("   %-8s %s   [%s]" % (p.device, p.description, p.hwid))
    if not ports:
        print("   none found -- the Teensy is not enumerated. Check the USB cable")
        print("   (charge-only cables are common) and that the board is powered.")
        return 1

    name = next((a for a in sys.argv[1:] if a.upper().startswith("COM")), None)
    if name is None:
        name = ports[0].device
    print("\nUsing %s at %d baud" % (name, BAUD))

    try:
        port = serial.Serial(name, BAUD, timeout=0.05, write_timeout=1.0)
    except (serial.SerialException, OSError) as exc:
        print("\nCOULD NOT OPEN %s" % name)
        print("   %s" % exc)
        print("\n   'Access is denied' means something else already owns the port:")
        print("   the Arduino Serial Monitor, a running copy of the GUI, or Unity.")
        print("   Close it and run this again -- Windows permits one owner only.")
        return 1

    print("   port opened")
    # A Teensy does not reset when the port opens, so whatever it was doing it
    # is still doing. It also ignores the baud rate entirely -- USB CDC always
    # runs at full speed -- so a baud mismatch cannot be the fault here.
    port.dtr = True
    time.sleep(0.3)
    port.reset_input_buffer()

    print("\n1. Unsolicited output")
    drain(port, 0.5, "-- expected, the board only speaks when spoken to")

    print("\n2. PING  (the one command that always answers)")
    send(port, "PING")
    got = drain(port, 1.0, "-- NO PONG")
    alive = b"PONG" in got

    if alive:
        print("      => board is alive and running this firmware")
    else:
        print("      => no answer. Either the sketch on the board is not this")
        print("         one (PING/PONG was added later), or nothing is running.")
        print("         Re-flash HighPrecisionStepperJuggler.ino and retry.")

    print("\n3. A deliberately malformed line")
    print("      (proves whether the parser is reached at all)")
    send(port, "THIS-IS-NOT-A-POSE")
    drain(port, 0.6, "-- silence is correct here: bad input is ignored, never reported")

    print("\n4. A bad marker  (the parser DOES complain about this one)")
    # Marker 99 instead of 11: the firmware prints a rejection even with
    # VERBOSE_SERIAL_LOGGING off, so a reply here proves the parse loop runs.
    send(port, "99.00000:0.00000:0.00000:0.00000:0.00000:0.50000")
    got = drain(port, 0.8, "-- NO rejection message")
    parses = b"Marker" in got
    if parses:
        print("      => the parser is running and reading our fields")
    else:
        print("      => the parser never rejected a bad marker, so the line is")
        print("         not reaching it. Check the cable and the flashed sketch.")

    if not move:
        print("\n5. Movement  (skipped -- pass --move to run it)")
    else:
        print("\n5. Movement")
        print("      origin, then +10 mm, then back. Watch the plate.")
        for label, pose in (("origin      ", (0.000, 0.0, 0.0, 1.0)),
                            ("up 10 mm    ", (0.010, 0.0, 0.0, 1.0)),
                            ("back to zero", (0.000, 0.0, 0.0, 1.0))):
            line = machine.serialize([pose])
            print("   %s" % label)
            send(port, line)
            drain(port, 1.4, "")

        print("\n      single-motor test: motor 0 only, 0.1 rad, 2 s")
        print("      (the same line Unity's SendTestMove sends)")
        send(port, "11.00000:0.10000:0.00000:0.00000:0.00000:2.00000")
        drain(port, 2.5, "")

    port.close()

    print("\n" + "=" * 62)
    print("board answers PING          : %s" % ("YES" if alive else "NO"))
    print("parser rejects a bad marker : %s" % ("YES" if parses else "NO"))
    if alive and parses:
        print("\nThe link is good in both directions. If the plate still does not")
        print("move, the fault is past the microcontroller: driver enable, motor")
        print("power, or the DM542T wiring -- not the serial protocol.")
    elif alive and not parses:
        print("\nOdd combination: PING is answered but the parser is silent about a")
        print("bad marker. That points at a different sketch on the board.")
    else:
        print("\nNo reply to anything. Re-flash the sketch from")
        print("Arduino/HighPrecisionStepperJuggler/, then run this again.")
    print("=" * 62)
    return 0 if alive else 2


if __name__ == "__main__":
    sys.exit(main())
