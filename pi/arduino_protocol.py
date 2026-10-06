"""
Pi -> Arduino messages on the serial link (Pi UART2, /dev/ttyAMA1 -> Mega Serial3, 38400 baud 8N1).

Shared by the vision engine (PoseEstimationJT_Optimized.py) and the tests. The Arduino side is handleCommand() in the
sketch. Every line is "$<body>*<XOR>\\r\\n", where XOR is the hex XOR of the characters between $ and *.

    $C,PI,<version>*XX           hello, about once a second while the vision engine has camera frames.
                                 Version 2: gestures come as PT messages and the GPIO wires are ignored.
                                 Version 1: an older engine that pulses the GPIO wires.
    $C,PT,<side><kind>,<id>*XX   a gesture on the camera's Left / Right half: P = T-pose (+1), C = cobra (-1).
                                 id = 1..255; each event is sent several times with the same id and applied once.
                                 The Arduino decides the team: camera-left = away, camera-right = home.

Pure Python with no dependencies, so the tests can import it anywhere.
"""

BAUD = 38400
HELLO_VERSION = 2
SIDES = ('L', 'R')        # the camera's left / right half
KINDS = ('P', 'C')        # T-pose point (+1) / cobra (-1)


def checksum(body):
    x = 0
    for ch in body:
        x ^= ord(ch)
    return x


def frame(body):
    """'C,PI,2' -> b'$C,PI,2*68\\r\\n'"""
    return ('$%s*%02X' % (body, checksum(body))).encode('ascii') + b'\r\n'


HELLO = frame('C,PI,%d' % HELLO_VERSION)


def event_line(side, kind, event_id):
    if side not in SIDES or kind not in KINDS or not 1 <= event_id <= 255:
        raise ValueError('bad gesture event: %r %r %r' % (side, kind, event_id))
    return frame('C,PT,%s%s,%d' % (side, kind, event_id))


def next_id(event_id):
    """1..255, wrapping 255 -> 1 (0 is never used)."""
    return event_id % 255 + 1


class ArduinoLink:
    """
    The vision engine's side of the serial link: everything the Pi tells the Arduino.

    * A hello every `period` seconds while camera frames are flowing (alive() called within the last `grace` seconds,
      which rides out a ~11 s USB camera re-connect). It is the Arduino's only sign of life from the Pi: "Raspberry Pi
      connected" on the first one, "disconnected" 4 s after the last, and it blinks the heartbeat pixel.
    * send_event('L'|'R', 'P'|'C'): a T-pose (+1) or cobra (-1) on the camera's left or right half. Each is written
      COPIES times, COPY_GAP apart, with the same id, and the Arduino applies an id once, so a copy lost to the
      Arduino's LED refresh (interrupts off for ~8 ms) doesn't matter. The Arduino decides which team owns which half.

    One thread does all the writing and leaves at least MIN_GAP between lines, so the Arduino reads each line before
    the next arrives (its receive buffer is 64 bytes). send_event() never blocks the caller. The port is shared with
    scoreboard_link.py; Linux writes each line in one piece. If the UART is missing (no dtoverlay=uart2) the writes
    quietly fail and the port is re-opened on the next line.

    For tests: `opener` returns a serial-like object (default: pyserial on `port`), and `clock` replaces
    time.monotonic.
    """
    COPIES = 3
    COPY_GAP = 0.15
    MIN_GAP = 0.04

    def __init__(self, port, period=1.0, grace=20.0, tpose_disabled_file=None, opener=None, clock=None, log=print):
        import random
        import threading
        import time
        self.port = port
        self.period = period
        self.grace = grace
        self.tpose_disabled_file = tpose_disabled_file
        self.opener = opener or self._open_serial
        self.clock = clock or time.monotonic
        self.log = log
        self.alive_until = 0.0
        self.ser = None
        self.lock = threading.Lock()
        self.pending = []                         # [due time, line], written in due order
        self.event_id = random.randint(1, 255)    # random start: a restarted engine doesn't repeat recent ids
        self.next_hello = None
        self.last_write = -1e9

    def _open_serial(self):
        import serial
        return serial.Serial(self.port, BAUD, timeout=0, write_timeout=0.2)

    def alive(self, now=None):
        self.alive_until = (self.clock() if now is None else now) + self.grace

    def start(self):
        import threading
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def send_event(self, side, kind):
        """Queue a gesture for the Arduino. Returns False (and sends nothing) while the phone's T-pose switch is off."""
        import os
        if self.tpose_disabled_file and os.path.exists(self.tpose_disabled_file):
            self.log("[GESTURES OFF] detection confirmed, not sent to the scoreboard (phone switch)")
            return False
        now = self.clock()
        with self.lock:
            self.event_id = next_id(self.event_id)
            line = event_line(side, kind, self.event_id)
            for i in range(self.COPIES):
                self.pending.append([now + i * self.COPY_GAP, line])
            self.pending.sort(key=lambda item: item[0])
            event_id = self.event_id
        self.log("[ARDUINO] gesture %s%s id %d" % (side, kind, event_id))
        return True

    def _write(self, line):
        try:
            if self.ser is None:
                self.ser = self.opener()
            self.ser.write(line)
        except Exception:
            try:
                if self.ser is not None:
                    self.ser.close()
            except Exception:
                pass
            self.ser = None

    def step(self):
        """One pass of the writer: queue a hello when due, then write at most one due line. Returns the line or None."""
        now = self.clock()
        if self.next_hello is None:
            self.next_hello = now
        if now >= self.next_hello:
            self.next_hello = max(self.next_hello + self.period, now)   # never a burst of hellos after a stall
            if now < self.alive_until:
                with self.lock:
                    self.pending.append([now, HELLO])
                    self.pending.sort(key=lambda item: item[0])
        if now - self.last_write < self.MIN_GAP:
            return None
        with self.lock:
            if not self.pending or self.pending[0][0] > now:
                return None
            line = self.pending.pop(0)[1]
        self._write(line)
        self.last_write = now
        return line

    def _run(self):
        import time
        while True:
            self.step()
            time.sleep(0.01)
