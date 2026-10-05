"""
Volleyball Scoreboard: Computer Vision Pose Recognition Engine (Production 2026)
Optimized for Raspberry Pi 4 Model B (Cortex-A72 @ 1.8GHz, 2GB RAM)
Camera: Arducam 1080P Low Light WDR USB Camera Module (Hardware MJPG, Wide Dynamic Range)

Core Capabilities:
1. 12-Player Dual-Half Inference with +12% Overlap:
   - Slices frame into Home and Away halves with generous overlap.
   - Prevents back-row players from being omitted by MoveNet's 6-person limit.
   - Arms reaching across the net are never clipped, even for players standing 4 ft away.
2. True Isotropic Pixel-Space Geometry:
   - All keypoints converted to sensor pixel coordinates (X_px, Y_px).
   - Eliminates the 2.37x vertical coordinate stretch bug; angles are 100% physically accurate.
3. Posture Recognition & False Positive Immunity:
   - Fast T-Pose: 2 consecutive frames, >= 135 deg elbow straightness. A gesture must be released before it can score again.
   - Surrender Cobra: >= 0.80s continuous hold (prevents false triggers on volleyball sets).
   - Torso spine lean capped to ~12°; arms checked at 90° ± 20° relative to the spine (camera roll on sand).
   - Adaptive wingspan scaling for wide-angle sideline foreshortening.
   - Tolerances dynamically scale with shoulder width; works for players 4 ft away to 30 ft away.
4. Continuous Live OLED Monitor:
   - Updates every 1.0 second with camera view and yellow net dividing line (<1.5% CPU overhead).
5. Asynchronous Background Capture Engine:
   - Background worker queue writes JPEGs without stalling the main loop or heartbeat.
   - Periodic frame every 3 s (~130 MB/hour) to limit SD writes; full-rate bursts around every confirmed pose.
6. Hardware MJPG Camera Stream with Auto-Reconnect Watchdog:
   - Hardware compressed MJPG eliminates USB 2.0 bus bottleneck.
   - Buffer size = 1 eliminates 4-frame queue lag.
   - Watchdog automatically recovers if camera overheats or resets.
"""

import os
import sys
import glob
import json
import collections
import time
import queue
import shutil
import threading
from datetime import datetime
os.environ.setdefault('OPENCV_LOG_LEVEL', 'ERROR')  # silence per-second V4L2 warnings while the camera is unplugged
import cv2 as cv
import numpy as np

# Hardware platform detection
IS_RPI = (os.name != 'nt') and (not sys.platform.startswith('darwin'))

if IS_RPI:
    import board
    from digitalio import DigitalInOut, Direction, Pull
    import tflite_runtime.interpreter as tflite
else:
    # Desktop simulation mocks
    class DigitalInOut:
        def __init__(self, pin):
            self.pin = pin
            self.value = 0
            self.direction = None
            self.pull = None
    class Direction:
        OUTPUT = 0
        INPUT = 1
    class Pull:
        UP = 0
    import tensorflow.lite as tflite

# Import OLED display if present on Pi
try:
    from myDisplayFunctions import displayOLED, clearDisplay
    HAS_OLED = True
except Exception:
    HAS_OLED = False
    def displayOLED(*args, **kwargs): pass
    def clearDisplay(): pass

# --- CONFIGURATION ---
MODEL_SEARCH_PATHS = [
    '/home/pi/Documents/resources/saved_model_192x256/model_float16_quant.tflite',
    'resources/saved_model_192x256/model_float16_quant.tflite',
    '/home/pi/Documents/resources/saved_model_256x256/model_float16_quant.tflite',
    'resources/saved_model_256x256/model_float16_quant.tflite',
    'movenet_multipose_lightning.tflite'
]
MODEL_PATH = next((p for p in MODEL_SEARCH_PATHS if os.path.exists(p)), 'movenet_multipose_lightning.tflite')

# 192x256 matches our ~1.37:1 half-court aspect ratio and reduces pixel load by 25%
if '192x256' in MODEL_PATH:
    INPUT_SIZE = [192, 256]  # [Height, Width]
else:
    INPUT_SIZE = [256, 256]

NUM_THREADS = int(os.environ.get('SCOREBOARD_THREADS', '4'))  # override for benchmarking without editing code
POSE_HOLD_FRAMES = 2              # T-Pose must be seen in this many of the last POSE_WINDOW_FRAMES frames
POSE_WINDOW_FRAMES = 3            # (2 of 3: one frame with a flickering wrist no longer resets the hold)
LIMB_CONF_THRESH = 0.15           # elbow/wrist keypoint confidence floor (shoulders use 0.20); wrists flicker
                                  # around 0.2 even when their position is steady
CLOSE_RANGE_SHOULDER_PX = 80.0    # close-range player: shoulders at least this wide (px) ...
CLOSE_RANGE_TOP_FRACTION = 0.15   # ... and within the top 15% of the frame (head and raised hands cut off)
COBRA_HOLD_SECONDS = 0.80         # Surrender cobra must be held for >= 0.8s (prevents triggers on sets)
SCORE_COOLDOWN = 3.0              # Seconds to wait after a point before accepting another
MAX_CENTER_DRIFT = 0.07           # Net center clamped to [0.43, 0.57]
SAVE_INTERVAL_SECONDS = 3.0       # Periodic capture interval: ~130 MB/hour (was 0.75 s / ~530 MB/hour). Fewer SD
                                  # writes = less exposure to power-cut damage; pose bursts cover the frames that matter
MAX_CAPTURE_DIR_BYTES = 5 * 1024 * 1024 * 1024  # 5.0 GB local storage cap
CROP_TOP_FRACTION = 0.02         # 0.0 was tested and was slightly worse on indoor close-range frames
CROP_BOTTOM_FRACTION = 0.92      # bottom 8% is foreground floor/sand
OVERLAP_MARGIN = 0.12             # 12% court width overlap (ensures close players' outstretched arms are visible)
HEARTBEAT_PERIOD = 1.0           # Arduino heartbeat toggle period (s); see HeartbeatThread
CAMERA_OUTAGE_GRACE = 20.0       # keep the heartbeat going this long without camera frames (USB re-connect takes ~11 s)
MIN_TPOSE_SHOULDER_PX = 22.0      # T-pose size floor. Measured scale: shoulder width ~= 270 px / distance (m)
                                  # (~100-120 px at 2.5 m), so 22 px ~= 12 m: the far sideline (~9-10 m, ~28 px)
                                  # counts, people more than ~2-3 m beyond the court do not.
MAIN_LOOP_STALL_SECONDS = 60.0    # MainLoopWatchdog: exit (systemd restarts us) if the loop stops for this long
STATUS_PRINT_SECONDS = 60.0       # Periodic fps / temperature / CPU clock line in the journal

# Power button: time-based hold (independent of frame rate). A button that is already pressed when
# the script starts is ignored until it is released, so a stuck or shorted button can never cause a
# shutdown on every boot (the Pi is hard to reach physically).
POWER_HOLD_SECONDS = 5.0

# OLED burn-in protection: the panel is only lit when someone is likely to look at it, and is
# blanked (all pixels off) the rest of the time.
OLED_BOOT_SECONDS = 300.0         # Aim-assist window after start: line the far net pole up with the center line
OLED_EVENT_SECONDS = 15.0         # Show the view after each confirmed point / cobra
OLED_WAKE_SECONDS = 30.0          # Show the view after a short power-button press

# Local capture paths
if IS_RPI:
    CAPTURE_BASE_DIR = '/home/pi/Documents/FieldCaptures'
else:
    CAPTURE_BASE_DIR = os.path.join(os.getcwd(), 'FieldCaptures')

CAPTURE_PERIODIC_DIR = os.path.join(CAPTURE_BASE_DIR, 'Periodic')
CAPTURE_CONFIRMED_DIR = os.path.join(CAPTURE_BASE_DIR, 'ConfirmedPoses')
POSE_EVENTS_DIR = os.path.join(CAPTURE_BASE_DIR, 'PoseEvents')   # see PoseEventLogger
POSE_EVENT_LOGGING = True         # T-pose tuning bursts + candidate log (PoseEventLogger); set False once tuning is done
EVENT_PRE_FRAMES = 20            # frames kept in RAM and saved before a confirmed point/cobra (~6 s, ~55 MB RAM)
EVENT_POST_FRAMES = 6            # frames saved after it
MAX_CONFIRMED_FILES = 2000        # ConfirmedPoses keeps the newest 2000 images (raw + annotated per point)
MAX_POSE_EVENTS = 300            # oldest event folders are deleted beyond this
CANDIDATE_LOG_MAX_BYTES = 50 * 1024 * 1024  # tpose_candidates.jsonl is rotated at this size

os.makedirs(CAPTURE_PERIODIC_DIR, exist_ok=True)
os.makedirs(CAPTURE_CONFIRMED_DIR, exist_ok=True)
os.makedirs(POSE_EVENTS_DIR, exist_ok=True)

# GPIO Pin Configuration (Pi 4 BCM mapping)
if IS_RPI:
    homeScorePin = DigitalInOut(board.D6)
    awayScorePin = DigitalInOut(board.D5)
    sparePin = DigitalInOut(board.D13)
    heartbeatPin = DigitalInOut(board.D26)
    powerOffButtonPin = DigitalInOut(board.D12)
    surrenderHomePin = DigitalInOut(board.D19)
    surrenderAwayPin = DigitalInOut(board.D21)

    homeScorePin.direction = Direction.OUTPUT
    awayScorePin.direction = Direction.OUTPUT
    sparePin.direction = Direction.OUTPUT
    heartbeatPin.direction = Direction.OUTPUT
    surrenderHomePin.direction = Direction.OUTPUT
    surrenderAwayPin.direction = Direction.OUTPUT

    powerOffButtonPin.direction = Direction.INPUT
    powerOffButtonPin.pull = Pull.UP

    homeScorePin.value = 0
    awayScorePin.value = 0
    sparePin.value = 0
    heartbeatPin.value = 0
    surrenderHomePin.value = 0
    surrenderAwayPin.value = 0
else:
    homeScorePin = DigitalInOut(6)
    awayScorePin = DigitalInOut(5)
    sparePin = DigitalInOut(13)
    heartbeatPin = DigitalInOut(26)
    powerOffButtonPin = DigitalInOut(12)
    surrenderHomePin = DigitalInOut(19)
    surrenderAwayPin = DigitalInOut(21)

# Keypoint indices
KP = {
    'nose': 0, 'left_eye': 1, 'right_eye': 2, 'left_ear': 3, 'right_ear': 4,
    'left_shoulder': 5, 'right_shoulder': 6, 'left_elbow': 7, 'right_elbow': 8,
    'left_wrist': 9, 'right_wrist': 10, 'left_hip': 11, 'right_hip': 12,
    'left_knee': 13, 'right_knee': 14, 'left_ankle': 15, 'right_ankle': 16
}


class CourtCameraStream:
    """
    High-performance, threaded camera capture engine designed for volleyball court operation:
    1. Zero-lag threaded grabber: eliminates OpenCV V4L2 queue lag.
    2. Hardware MJPG codec: avoids USB 2.0 bus bottleneck.
    3. Low-latency buffer: CAP_PROP_BUFFERSIZE = 1.
    4. Auto-reconnection watchdog: recovers if camera overheats or resets.
    """
    FROZEN_SECONDS = 5.0   # identical frames for this long = hung camera (real sensors always have noise)

    def __init__(self, src=0, width=1280, height=720):
        self.src = src
        self.width = width
        self.height = height
        self.cap = None
        self.frame = None
        self.frame_time = 0.0
        self.stopped = False
        self.lock = threading.Lock()
        self._init_camera()

    def _resolve_source(self):
        """
        The USB camera can drop off the bus and re-enumerate under a different index (seen in the field:
        it disconnected 3 times during boot and came back as /dev/video1 while the dead /dev/video0 was
        still held open). The udev by-id symlink always points at the camera's current capture node.
        """
        if isinstance(self.src, int) and IS_RPI:
            by_id = sorted(glob.glob('/dev/v4l/by-id/*-video-index0'))
            if by_id:
                return by_id[0]
        return self.src

    def _init_camera(self):
        if self.cap is not None:
            try: self.cap.release()
            except Exception: pass
        with self.lock:
            self.frame = None  # never serve a frame from before the reconnect
        source = self._resolve_source()
        if isinstance(source, str) and source.startswith('/dev/'):
            self.cap = cv.VideoCapture(source, cv.CAP_V4L2)
        else:
            self.cap = cv.VideoCapture(source)
        opened = self.cap.isOpened()
        now = time.monotonic()
        if opened != getattr(self, '_last_open_ok', None) or (now - getattr(self, '_last_open_log', -1e9)) > 60.0:
            print(f"[CAMERA] Opening {source}: {'OK' if opened else 'FAILED (retrying every 2 s)'}")
            self._last_open_ok = opened
            self._last_open_log = now
        if self.cap.isOpened():
            try:
                self.cap.set(cv.CAP_PROP_FOURCC, cv.VideoWriter_fourcc(*'MJPG'))
                self.cap.set(cv.CAP_PROP_FRAME_WIDTH, self.width)
                self.cap.set(cv.CAP_PROP_FRAME_HEIGHT, self.height)
                self.cap.set(cv.CAP_PROP_BUFFERSIZE, 1)
            except Exception: pass
            ret, frame = self.cap.read()
            if ret and frame is not None:
                with self.lock:
                    self.frame = frame
                    self.frame_time = time.monotonic()

    def start(self):
        self.stopped = False
        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()
        return self

    def _update(self):
        # The reader thread must never die: an unexpected exception (e.g. inside a USB re-open) would
        # otherwise leave the scoreboard blind until the next reboot. Log it, drop the capture and retry.
        while not self.stopped:
            try:
                self._read_frames()
            except Exception as e:
                print(f"[CAMERA] Reader error: {e!r} - re-opening camera in 2 s")
                try:
                    self.cap.release()
                except Exception:
                    pass
                self.cap = None
                time.sleep(2.0)

    def _read_frames(self):
        failed_count = 0
        last_sig = None
        last_change_time = time.monotonic()
        while not self.stopped:
            if self.cap is None or not self.cap.isOpened():
                time.sleep(2.0)
                self._init_camera()
                continue
            ret, frame = self.cap.read()
            if ret and frame is not None:
                failed_count = 0
                # Hung-camera check: a live sensor never produces bit-identical frames for seconds
                sig = frame[::32, ::32].tobytes()
                now = time.monotonic()
                if sig != last_sig:
                    last_sig = sig
                    last_change_time = now
                elif ((now - last_change_time) > self.FROZEN_SECONDS and not isinstance(self.src, str)
                      and np.frombuffer(sig, dtype=np.uint8).std() > 3.0):  # skip all-black frames (lens covered / night)
                    print("[CAMERA WATCHDOG] Camera is returning identical frames. Re-opening camera...")
                    self._init_camera()
                    last_sig = None
                    last_change_time = time.monotonic()
                    continue
                with self.lock:
                    self.frame = frame
                    self.frame_time = time.monotonic()
            else:
                if isinstance(self.src, str) and os.path.exists(self.src):
                    self.cap.set(cv.CAP_PROP_POS_FRAMES, 0)
                    time.sleep(0.03)
                    continue
                failed_count += 1
                if failed_count > 15:
                    print("[CAMERA WATCHDOG] Frame stream stalled (possible USB glitch or overheat). Re-opening camera...")
                    self._init_camera()
                    failed_count = 0
                time.sleep(0.01)

    def read(self, max_age=2.0):
        # Never hand out a stale frame: if the camera has died, re-processing the last frame forever
        # would keep the heartbeat alive and could re-score a frozen T-pose every cooldown.
        with self.lock:
            if self.frame is None or (time.monotonic() - self.frame_time) > max_age:
                return None
            return self.frame.copy()

    def stop(self):
        self.stopped = True
        if hasattr(self, 'thread'):
            try: self.thread.join(timeout=1.0)
            except Exception: pass
        if self.cap is not None:
            try: self.cap.release()
            except Exception: pass


class PowerButtonMonitor:
    """
    Polls the power button every 0.1 s on its own thread, so a hold is timed in real seconds and the
    button still works when the main loop is slow or waiting for a dead camera.
    - Holding for hold_seconds sets shutdown_requested (the main loop performs the shutdown).
    - A button that already reads pressed at startup (stuck/shorted) is ignored until it is released,
      so a bad button can never shut the Pi down on every boot.
    """
    def __init__(self, pin, hold_seconds):
        self.pin = pin
        self.hold_seconds = hold_seconds
        self.pressed_since = 0.0
        self.last_press_time = -1e9
        self.counter = 0                  # 0-10 scale for the OLED shutdown countdown bar
        self.shutdown_requested = False

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def _run(self):
        try:
            enabled = bool(self.pin.value)    # pull-up: True = released
        except Exception:
            enabled = False
        if not enabled:
            print("[POWER BUTTON] Reads pressed at startup - ignoring it until it is released")
        while not self.shutdown_requested:
            try:
                pressed = not self.pin.value
            except Exception:
                pressed = False
            now = time.monotonic()
            if not pressed:
                enabled = True
                self.pressed_since = 0.0
                self.counter = 0
            elif enabled:
                if self.pressed_since == 0.0:
                    self.pressed_since = now
                self.last_press_time = now
                held = now - self.pressed_since
                self.counter = min(10, int(10 * held / self.hold_seconds))
                if held >= self.hold_seconds:
                    self.shutdown_requested = True
            time.sleep(0.1)


class HeartbeatThread:
    """
    Toggles the Arduino heartbeat pin at a steady HEARTBEAT_PERIOD, but only while the main loop is
    processing live frames (alive() called within the last CAMERA_OUTAGE_GRACE seconds, which rides out a
    ~11 s USB camera re-connect without the Arduino announcing a disconnect). A steady 1.0 s period is
    accepted by every Arduino firmware version: the original (> 300 ms, consecutive periods within
    ±700 ms), and the fixed one; it also avoids the < 700 ms periods that the intermediate
    `unsigned long` firmware mishandled. Toggling from the main loop instead made the period depend
    on frame time (anything from 350 ms to several seconds).
    """
    def __init__(self, pin, period, hello=None):
        self.pin = pin
        self.period = period
        self.alive_until = 0.0
        self.value = 0
        self.hello = hello

    def alive(self, now, grace=CAMERA_OUTAGE_GRACE):
        self.alive_until = now + grace

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def _run(self):
        next_toggle = time.monotonic()
        while True:
            next_toggle += self.period
            time.sleep(max(0.0, next_toggle - time.monotonic()))
            if time.monotonic() < self.alive_until:
                self.value = 1 - self.value
                try:
                    self.pin.value = self.value
                except Exception:
                    pass
                if self.hello is not None:
                    # Wait out the Arduino's reaction to the toggle: it refreshes its LED strip (~8 ms with
                    # interrupts off), which would eat the bytes of a hello sent at the same moment.
                    time.sleep(0.3)
                    self.hello.send()


class ArduinoHello:
    """
    Serial handshake with the Arduino. While the vision engine is really running (same condition as the heartbeat:
    camera frames are flowing), tell the Arduino so about once a second. The Arduino only acts on score pulses while it
    has heard this recently, so the Pi's GPIO pins doing odd things during boot, shutdown or a hang can never change the
    score. The port is shared with scoreboard_link.py (which only reads from it); if the UART is not enabled
    (no dtoverlay=uart2) this quietly does nothing.
    """
    LINE = b'$C,PI,1*6B\r\n'    # "$C,PI,1*XX": checksummed like every Pi -> Arduino command

    def __init__(self, port):
        self.port = port
        self.ser = None

    def send(self):
        try:
            if self.ser is None:
                import serial
                self.ser = serial.Serial(self.port, 38400, timeout=0, write_timeout=0.2)
            self.ser.write(self.LINE)
        except Exception:
            try:
                if self.ser is not None:
                    self.ser.close()
            except Exception:
                pass
            self.ser = None


class MainLoopWatchdog:
    """
    If the main loop stops iterating (a hang inside OpenCV/TFLite/SPI, a deadlock), exit the process
    so systemd restarts the scoreboard (Restart=always) instead of leaving it frozen. The loop keeps
    iterating while it waits for a disconnected camera, so a missing camera does not trigger this.
    """
    def __init__(self, stall_seconds):
        self.stall_seconds = stall_seconds
        self.last_tick = time.monotonic()

    def tick(self):
        self.last_tick = time.monotonic()

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def _run(self):
        while True:
            time.sleep(5.0)
            stalled = time.monotonic() - self.last_tick
            if stalled > self.stall_seconds:
                print(f"[WATCHDOG] Main loop stalled for {stalled:.0f} s - exiting so systemd restarts the scoreboard")
                sys.stdout.flush()
                os._exit(1)


def shutdown_pi(vs):
    print("Power button held: Shutting down safely!")
    vs.stop()
    clearDisplay()
    # Runs as a systemd service (no desktop session), so polkit denies a plain
    # `shutdown` for user pi; pi has passwordless sudo.
    os.system("sudo -n /sbin/shutdown -h now")


def calculate_angle_px(a, b, c):
    """Calculates angle ABC (vertex at B) in degrees using true isotropic pixel coordinates."""
    v1 = np.array([a[0] - b[0], a[1] - b[1]], dtype=np.float32)
    v2 = np.array([c[0] - b[0], c[1] - b[1]], dtype=np.float32)
    norm = np.linalg.norm(v1) * np.linalg.norm(v2)
    if norm < 1e-4:
        return 180.0
    cos_ang = np.clip(np.dot(v1, v2) / norm, -1.0, 1.0)
    return float(np.degrees(np.arccos(cos_ang)))


def check_t_pose(keypoints_px, player_global_x=0.50, conf_thresh=0.20, limb_conf_thresh=LIMB_CONF_THRESH,
                 expected_lean_deg=0.0, frame_h=None, diag=None):
    """
    Checks if pixel-space keypoints represent a true T-Pose:
    - keypoints_px: [17, 3] where [x_px, y_px, score] in true sensor pixels.
    - Operates in true isotropic pixel space (eliminates vertical coordinate stretch).
    - Works for players 4 ft away (shoulder width ~300-500px) to 30 ft away (~25px).
    """
    ls = keypoints_px[KP['left_shoulder']]
    rs = keypoints_px[KP['right_shoulder']]
    le = keypoints_px[KP['left_elbow']]
    re = keypoints_px[KP['right_elbow']]
    lw = keypoints_px[KP['left_wrist']]
    rw = keypoints_px[KP['right_wrist']]
    lh = keypoints_px[KP['left_hip']]
    rh = keypoints_px[KP['right_hip']]

    # Every check is evaluated and recorded (instead of returning at the first failure) so that
    # PoseEventLogger can show exactly which thresholds a near-miss T-pose failed.
    fails = []
    m = {}

    # Mirrored labels: with the head cut off (players close to the ground-level camera) MoveNet can't
    # see the face, guesses the player is facing away, and swaps left/right for the whole body. A
    # T-pose is symmetric, so swap the labels back instead of failing the joint-order check.
    if ls[0] < rs[0]:
        ls, rs, le, re, lw, rw, lh, rh = rs, ls, re, le, rw, lw, rh, lh
        m['swapped_lr'] = True

    # Missing wrists: an unusable wrist (low confidence, or not beyond its elbow) is put where a straight
    # forearm would be (elbow + upper arm). Normally only ONE wrist may be projected and the other arm
    # must be complete, which keeps poses like a double-biceps flex from passing. Close-range players
    # (big shoulders right at the top of the frame, head cut off) usually lose BOTH wrists while their
    # elbows stay accurate, so for them both may be projected.
    def wrist_usable(el, wr, outward):
        return wr[2] >= limb_conf_thresh and (wr[0] - el[0]) * outward > 0
    l_usable, r_usable = wrist_usable(le, lw, 1.0), wrist_usable(re, rw, -1.0)
    close_range = (frame_h is not None and abs(ls[0] - rs[0]) >= CLOSE_RANGE_SHOULDER_PX
                   and max(ls[1], rs[1]) <= CLOSE_RANGE_TOP_FRACTION * frame_h)
    if l_usable != r_usable or (close_range and not l_usable and not r_usable):
        projected = []
        for name, sh, el, usable in (('left', ls, le, l_usable), ('right', rs, re, r_usable)):
            if usable or el[2] < limb_conf_thresh or sh[2] < conf_thresh:
                continue
            proj = np.array([2.0 * el[0] - sh[0], 2.0 * el[1] - sh[1], limb_conf_thresh], dtype=np.float32)
            if name == 'left':
                lw = proj
            else:
                rw = proj
            projected.append(name)
        if projected:
            m['projected_wrist'] = '+'.join(projected)
            m['close_range'] = close_range

    essential = [ls, rs, le, re, lw, rw]
    m['min_conf'] = round(float(min(p[2] for p in essential)), 2)
    if min(ls[2], rs[2]) < conf_thresh or min(le[2], re[2], lw[2], rw[2]) < limb_conf_thresh:
        fails.append('low_conf')

    # Shoulder width in true pixels
    shoulder_w = abs(ls[0] - rs[0])
    m['shoulder_w'] = round(float(shoulder_w), 1)
    # Allows players 10m away in back row (22px) up to 4 ft away in front row (550px)
    if shoulder_w < MIN_TPOSE_SHOULDER_PX or shoulder_w > 550.0:
        fails.append('shoulder_w')
    shoulder_w = max(shoulder_w, 1.0)

    # 1. Torso Spine Vector (Neutralizes camera roll tilt on uneven sand)
    has_hips = (lh[2] >= 0.15 and rh[2] >= 0.15)
    spine_len = 0.0
    if has_hips:
        hip_mid = (lh[:2] + rh[:2]) / 2.0
        sho_mid = (ls[:2] + rs[:2]) / 2.0
        # In image coordinates y=0 is top, so upright shoulders have lower y than hips
        if sho_mid[1] > hip_mid[1]:
            fails.append('inverted')  # Inverted or diving

        spine_v = np.array([sho_mid[0] - hip_mid[0], sho_mid[1] - hip_mid[1]], dtype=np.float32)
        spine_len = np.linalg.norm(spine_v)
        # Remove the lean the camera itself adds at this x position (KeystoneEstimator), then cap the
        # remaining (real) lean to ~12°. Arm angles below are measured against this corrected spine.
        # The correction is only used when it reduces the lean, so a wrong estimate (e.g. right after
        # the camera is re-aimed) can never make this check stricter than without it.
        lean_raw = np.arctan2(spine_v[0], -spine_v[1])
        lean = lean_raw - np.radians(expected_lean_deg)
        if abs(lean_raw) <= abs(lean):
            lean = lean_raw
        spine_v = np.array([np.sin(lean), -np.cos(lean)], dtype=np.float32) * spine_len
        m['tilt_deg'] = round(float(np.degrees(lean)), 1)
        m['expected_lean_deg'] = round(float(expected_lean_deg), 1)
        if abs(spine_v[1]) > 15.0 and abs(np.degrees(lean)) > 12.0:
            fails.append('tilt')  # Excessive sideways lean

    # 2. Elbows and wrists at shoulder height, measured along the player's own body axis (hips ->
    # shoulders) rather than image-vertical: when the whole body appears tilted (keystone lean at the
    # frame edges), a perfect T is tilted too and its wrists sit ~0.4-0.5 shoulder widths above/below
    # shoulder height in raw image coordinates. The tilt check above still limits how far the body leans.
    # The hip->shoulder axis is unreliable for some close-range frames (head cut off, hips misplaced), so
    # the better of body-axis and image-vertical measurements is used: never stricter than image-only.
    # Tolerance scales with shoulder width (close players get more pixels of leeway).
    y_tol = max(14.0, 0.35 * shoulder_w)
    axes = [np.array([0.0, -1.0], dtype=np.float32)]
    if has_hips and np.linalg.norm(hip_mid - sho_mid) > 15.0:
        axes.append((sho_mid - hip_mid) / np.linalg.norm(sho_mid - hip_mid))

    def offsets_along(up):
        h = [float(np.dot(p[:2], up)) for p in (ls, rs, le, re, lw, rw)]
        shoulder_h = (h[0] + h[1]) / 2.0
        return [abs(h[0] - h[1])] + [abs(v - shoulder_h) for v in h[2:]]

    y_offsets = min((offsets_along(up) for up in axes), key=max)
    m['y_off_max_over_tol'] = round(float(max(y_offsets) / y_tol), 2)   # must be <= 1.0
    if max(y_offsets) > y_tol:
        fails.append('height_align')

    # 3. Arm perpendicularity relative to spine (in true pixel coordinates)
    if spine_len > 15.0:
        left_arm_v = np.array([lw[0] - ls[0], lw[1] - ls[1]], dtype=np.float32)
        right_arm_v = np.array([rw[0] - rs[0], rw[1] - rs[1]], dtype=np.float32)

        def angle_to_spine(v):
            dot = np.dot(spine_v, v)
            n = np.linalg.norm(spine_v) * np.linalg.norm(v)
            if n < 1e-4: return 90.0
            return float(np.degrees(np.arccos(np.clip(dot / n, -1.0, 1.0))))

        left_ang = angle_to_spine(left_arm_v)
        right_ang = angle_to_spine(right_arm_v)
        m['arm_spine_deg'] = [round(left_ang), round(right_ang)]

        # 90° ± 20°: the spine itself can lean ~6° from lens distortion at the frame edges
        if not (70.0 <= left_ang <= 110.0) or not (70.0 <= right_ang <= 110.0):
            fails.append('arm_spine_angle')

    # 4. Strict horizontal joint ordering (RightWrist < RightElbow < RightShoulder < LeftShoulder < LeftElbow < LeftWrist)
    if not (rw[0] < re[0] < rs[0] < ls[0] < le[0] < lw[0]):
        fails.append('joint_order')

    # 5. Wide-Angle Edge Adaptation
    dist_from_center = abs(player_global_x - 0.50)
    if dist_from_center > 0.25:
        min_wingspan_ratio = max(1.60, 1.85 - 0.60 * (dist_from_center - 0.25))
    else:
        min_wingspan_ratio = 1.85

    wingspan = abs(lw[0] - rw[0])
    m['wingspan_ratio'] = round(float(wingspan / shoulder_w), 2)
    m['wingspan_min'] = round(float(min_wingspan_ratio), 2)
    if wingspan / shoulder_w < min_wingspan_ratio:
        fails.append('wingspan')

    # 6. Strict Elbow Straightness in true pixel space (>= 135°)
    left_elbow_angle = calculate_angle_px(ls[:2], le[:2], lw[:2])
    right_elbow_angle = calculate_angle_px(rs[:2], re[:2], rw[:2])
    m['elbow_deg'] = [round(left_elbow_angle), round(right_elbow_angle)]
    if left_elbow_angle < 135.0 or right_elbow_angle < 135.0:
        fails.append('elbow_straight')

    if diag is not None:
        diag['fails'] = fails
        diag['metrics'] = m
    return not fails


def check_surrender_cobra(keypoints_px, conf_thresh=0.20):
    """
    Checks if pixel-space keypoints represent a true Surrender Cobra:
    - Hands resting on/over top of head
    - Hands close together horizontally
    - Elbows bent sharply (angle 35 to 100 degrees) and flared out wider than shoulders
    """
    ls = keypoints_px[KP['left_shoulder']]
    rs = keypoints_px[KP['right_shoulder']]
    le = keypoints_px[KP['left_elbow']]
    re = keypoints_px[KP['right_elbow']]
    lw = keypoints_px[KP['left_wrist']]
    rw = keypoints_px[KP['right_wrist']]
    nose = keypoints_px[KP['nose']]
    leye = keypoints_px[KP['left_eye']]
    reye = keypoints_px[KP['right_eye']]

    # Same mirrored-label fix as check_t_pose (the pose is symmetric)
    if ls[0] < rs[0]:
        ls, rs, le, re, lw, rw = rs, ls, re, le, rw, lw

    essential = [ls, rs, le, re, lw, rw, nose]
    if any(p[2] < conf_thresh for p in essential):
        return False

    shoulder_w = abs(ls[0] - rs[0])
    if shoulder_w < 20.0 or shoulder_w > 550.0:
        return False

    # Estimate head top
    eyes = [p[1] for p in [leye, reye, nose] if p[2] >= 0.15]
    head_top_y = min(eyes) if eyes else nose[1]
    head_h = max(20.0, 0.45 * shoulder_w)

    # 1. Wrists must be above or at top of head
    if lw[1] > head_top_y + 0.18 * head_h or rw[1] > head_top_y + 0.18 * head_h:
        return False

    # 2. Hands near head centerline (measured on test video: hands-on-head wrists sit ~0.5 shoulder
    #    widths from the nose and ~0.9-1.0 shoulder widths apart)
    if abs(lw[0] - nose[0]) > 0.75 * shoulder_w or abs(rw[0] - nose[0]) > 0.75 * shoulder_w:
        return False

    if abs(lw[0] - rw[0]) > 1.20 * shoulder_w:
        return False

    # 3. Elbows flared out wider than shoulders
    if re[0] > rs[0] - 0.08 * shoulder_w: return False
    if le[0] < ls[0] + 0.08 * shoulder_w: return False

    # 4. Acute elbow angles in true pixel coordinates
    left_elbow_angle = calculate_angle_px(ls[:2], le[:2], lw[:2])
    right_elbow_angle = calculate_angle_px(rs[:2], re[:2], rw[:2])
    if not (35.0 <= left_elbow_angle <= 100.0) or not (35.0 <= right_elbow_angle <= 100.0):
        return False

    return True


class KeystoneEstimator:
    """
    The camera sits on the ground looking slightly up through a wide-angle lens, so upright people
    near the left/right edges appear to lean outward (measured Oct 1 indoors: lean ≈ -28°·(x-0.5) + 2.4°,
    i.e. ~10° at the frame edges). check_t_pose subtracts this expected lean before its tilt and
    arm-angle checks. The line is re-fitted every 60 s from upright people in view, so it follows
    the camera when it is re-aimed; the fit is clamped so a bad estimate can't go wild.
    """
    def __init__(self, slope=-28.0, offset=2.4):
        self.slope = slope
        self.offset = offset
        self.samples = collections.deque(maxlen=400)
        self.last_fit = time.monotonic()

    def lean_deg(self, x):
        return self.slope * (x - 0.5) + self.offset

    def add(self, x, kps_px):
        """Records one upright, confidently detected person (x in 0..1, keypoints in pixels)."""
        if min(kps_px[i][2] for i in (5, 6, 11, 12)) < 0.40:
            return
        sho = (kps_px[5][:2] + kps_px[6][:2]) / 2.0
        hip = (kps_px[11][:2] + kps_px[12][:2]) / 2.0
        v = sho - hip
        if v[1] > -40.0:   # torso must be clearly vertical-ish and big enough to measure
            return
        self.samples.append((x, float(np.degrees(np.arctan2(v[0], -v[1])))))

    def update(self, t):
        if (t - self.last_fit) < 60.0 or len(self.samples) < 40:
            return
        self.last_fit = t
        a = np.array(self.samples)
        if np.ptp(a[:, 0]) < 0.4:   # need people spread across the frame to fit a slope
            return
        fit = np.polyfit(a[:, 0] - 0.5, a[:, 1], 1)
        resid = np.abs(a[:, 1] - np.polyval(fit, a[:, 0] - 0.5))
        keep = resid <= 2.5 * np.median(resid) + 1e-6   # drop bending/jumping outliers, refit
        if keep.sum() >= 20:
            fit = np.polyfit(a[keep, 0] - 0.5, a[keep, 1], 1)
        self.slope = float(np.clip(0.7 * self.slope + 0.3 * fit[0], -45.0, 0.0))
        self.offset = float(np.clip(0.7 * self.offset + 0.3 * fit[1], -6.0, 6.0))


class NetCenterCalibrator:
    """
    Safe auto-calibration engine with strict drift bounds:
    - Never moves beyond +/- MAX_CENTER_DRIFT from 0.50 ([0.43, 0.57]).
    - Filters candidate players to only upright standing players.
    - Evaluates candidate midpoints over a 30s window (10s before first point).
    """
    def __init__(self, initial_center=0.50, max_drift=MAX_CENTER_DRIFT):
        self.center_x = initial_center
        self.nominal_center = initial_center
        self.max_drift = max_drift
        self.first_point_scored = False
        self.last_calibration_time = time.monotonic()
        self.quality_frames = []

    @property
    def interval(self):
        return 30.0 if self.first_point_scored else 10.0

    def add_quality_frame(self, left_player_xs, right_player_xs):
        """Only accept frames where at least 1 player on left and 1 on right are clearly standing."""
        if len(left_player_xs) >= 1 and len(right_player_xs) >= 1:
            med_l = np.median(left_player_xs)
            med_r = np.median(right_player_xs)
            if (med_r - med_l) > 0.15:
                self.quality_frames.append((med_l, med_r))

    def update(self, t):
        if (t - self.last_calibration_time) >= self.interval:
            self.last_calibration_time = t
            if len(self.quality_frames) >= 4:
                candidates = [(l + r) / 2.0 for (l, r) in self.quality_frames]
                best_candidate = float(np.median(candidates))
                min_allowed = self.nominal_center - self.max_drift  # 0.43
                max_allowed = self.nominal_center + self.max_drift  # 0.57
                clamped_candidate = float(np.clip(best_candidate, min_allowed, max_allowed))

                delta = abs(clamped_candidate - self.center_x)
                if delta > 0.015:
                    old = self.center_x
                    self.center_x = float(0.70 * self.center_x + 0.30 * clamped_candidate)
                    print(f"[NET CALIBRATION] Adjusted: {old:.3f} -> {self.center_x:.3f} (clamped within {min_allowed:.2f}-{max_allowed:.2f})")

            self.quality_frames = []

    def mark_first_point(self, t):
        if not self.first_point_scored:
            self.first_point_scored = True
            self.last_calibration_time = t
            print("[NET CALIBRATION] First point scored! Switched to 30s in-game drift checks.")


def atomic_write_bytes(path, data):
    """
    Power-cut-safe file write: write a temp file, flush it to the SD card (fsync), then rename it into
    place. The scoreboard is often switched off at the power switch or runs its battery flat; a plain
    write that is cut off leaves a 0-byte or truncated file (19 such JPEGs were found). With rename,
    the final name either holds the complete file or does not exist.
    """
    tmp = path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def atomic_write_jpeg(path, image, quality):
    ok, buf = cv.imencode('.jpg', image, [cv.IMWRITE_JPEG_QUALITY, quality])
    if ok:
        atomic_write_bytes(path, buf.tobytes())


def next_session_id(base_dir):
    """
    Boot/session counter used as a filename prefix (S00042_...). The Pi has no clock battery: after an
    unclean shutdown it boots with the time from its last hourly save, and at the courts (no internet)
    it never corrects it, so timestamps can go backwards. The "delete oldest" rotation sorts by name,
    and the session prefix keeps that order correct across reboots. If the counter file was damaged by
    a power cut, the highest session seen in existing capture names is used instead.
    """
    counter_path = os.path.join(base_dir, 'session_counter.txt')
    best = 0
    try:
        with open(counter_path) as f:
            best = int(f.read().strip())
    except Exception:
        pass
    for sub_dir in ('PoseEvents', 'ConfirmedPoses'):
        try:
            for name in os.listdir(os.path.join(base_dir, sub_dir)):
                if name.startswith('S') and name[1:6].isdigit():
                    best = max(best, int(name[1:6]))
        except Exception:
            pass
    session = best + 1
    try:
        atomic_write_bytes(counter_path, str(session).encode())
    except Exception:
        pass
    return session


class AsyncCaptureSaver:
    """
    Asynchronous disk writing engine:
    - Dedicated background thread writes JPEGs via queue.
    - Main computer vision loop NEVER blocks on SD card I/O.
    - Enforces 5.0 GB total storage limit with FIFO rotation.
    - Halts saving if free disk space drops below 2.0 GB.
    """
    def __init__(self, base_dir=CAPTURE_BASE_DIR, max_bytes=MAX_CAPTURE_DIR_BYTES):
        self.base_dir = base_dir
        self.periodic_dir = os.path.join(base_dir, 'Periodic')
        self.confirmed_dir = os.path.join(base_dir, 'ConfirmedPoses')
        self.max_bytes = max_bytes
        # Bounded so a slow SD card can't make queued full-size frames eat the Pi's RAM (~2.7 MB each)
        self.queue = queue.Queue(maxsize=40)
        self.stopped = False
        self.save_counter = 0
        self.session_tag = 'S%05d' % next_session_id(base_dir)
        print(f"[CAPTURE] Session {self.session_tag}")

        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def _cleanup_after_power_loss(self):
        """Removes leftovers of writes interrupted by a power cut: *.tmp files and 0-byte images."""
        removed = 0
        for dirpath, _, filenames in os.walk(self.base_dir):
            for f in filenames:
                path = os.path.join(dirpath, f)
                try:
                    if f.endswith('.tmp') or (f.endswith('.jpg') and os.path.getsize(path) == 0):
                        os.remove(path)
                        removed += 1
                except Exception:
                    pass
        if removed:
            print(f"[CAPTURE] Removed {removed} incomplete files left by an unclean shutdown")

    def _worker(self):
        try:
            self._cleanup_after_power_loss()
        except Exception as e:
            print(f"[ASYNC CAPTURE ERR] cleanup: {e}")
        while not self.stopped:
            try:
                task = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                kind, args = task
                if not self._check_disk_safety():
                    continue

                if kind == 'periodic':
                    frame, timestamp = args
                    filename = os.path.join(self.periodic_dir, f"frame_{self.session_tag}_{timestamp}.jpg")
                    atomic_write_jpeg(filename, frame, 80)
                elif kind == 'confirmed':
                    raw_frame, debug_frame, prefix = args
                    atomic_write_jpeg(os.path.join(self.confirmed_dir, f"{self.session_tag}_{prefix}_raw.jpg"), raw_frame, 85)
                    atomic_write_jpeg(os.path.join(self.confirmed_dir, f"{self.session_tag}_{prefix}_annotated.jpg"), debug_frame, 85)
                elif kind == 'event':
                    self._write_event(*args)
                elif kind == 'jsonl':
                    path, line = args
                    if os.path.exists(path) and os.path.getsize(path) > CANDIDATE_LOG_MAX_BYTES:
                        os.replace(path, path + '.1')
                    with open(path, 'a') as f:
                        f.write(line + '\n')

                self.save_counter += 1
                if self.save_counter % 150 == 0:
                    self._enforce_cap()
            except Exception as e:
                print(f"[ASYNC CAPTURE ERR] {e}")
            finally:
                self.queue.task_done()

    def _check_disk_safety(self):
        try:
            total, used, free = shutil.disk_usage(self.base_dir)
            return free >= (2 * 1024 * 1024 * 1024)
        except Exception:
            return True

    def _enforce_cap(self):
        try:
            def size_or_zero(path):
                try:
                    return os.path.getsize(path)
                except OSError:   # deleted meanwhile (e.g. someone cleaning captures over Samba)
                    return 0
            total_size = sum(
                size_or_zero(os.path.join(dirpath, f))
                for dirpath, _, filenames in os.walk(self.base_dir)
                for f in filenames
            )
            if total_size > self.max_bytes:
                periodic_files = [
                    os.path.join(self.periodic_dir, f)
                    for f in os.listdir(self.periodic_dir)
                    if f.endswith('.jpg')
                ]
                periodic_files.sort()   # names: frame_S<session>_<time> -> oldest first, even if the clock jumped
                for f in periodic_files[:250]:
                    try: os.remove(f)
                    except Exception: pass
        except Exception:
            pass
        try:
            confirmed = sorted(f for f in os.listdir(self.confirmed_dir) if f.endswith('.jpg'))  # timestamp names
            for f in confirmed[:max(0, len(confirmed) - MAX_CONFIRMED_FILES)]:
                try: os.remove(os.path.join(self.confirmed_dir, f))
                except Exception: pass
        except Exception:
            pass
        try:
            events = sorted(d for d in os.listdir(POSE_EVENTS_DIR)
                            if os.path.isdir(os.path.join(POSE_EVENTS_DIR, d)))  # names start with a timestamp
            for d in events[:max(0, len(events) - MAX_POSE_EVENTS)]:
                shutil.rmtree(os.path.join(POSE_EVENTS_DIR, d), ignore_errors=True)
        except Exception:
            pass

    def _write_event(self, name, frames, trigger_no):
        event_dir = os.path.join(POSE_EVENTS_DIR, name)
        os.makedirs(event_dir, exist_ok=True)
        meta = []
        for i, rec in enumerate(frames):
            rel = rec['frame_no'] - trigger_no
            tag = 'TRIGGER' if rel == 0 else ('pre%d' % rel if rel < 0 else 'post+%d' % rel)
            atomic_write_jpeg(os.path.join(event_dir, f"{i:02d}_{tag}.jpg"), annotate_pose_record(rec, rel), 80)
            entry = {k: v for k, v in rec.items() if k != 'image'}
            entry['relative_frame'] = rel
            meta.append(entry)
        atomic_write_bytes(os.path.join(event_dir, 'frames.json'),
                           json.dumps(meta, indent=1, default=_json_default).encode())
        print(f"[POSE EVENT] Saved {len(frames)} frames to {event_dir}")

    def save_event(self, name, frames, trigger_no):
        try:
            self.queue.put_nowait(('event', (name, frames, trigger_no)))
        except queue.Full:
            pass

    def append_jsonl(self, path, line):
        try:
            self.queue.put_nowait(('jsonl', (path, line)))
        except queue.Full:
            pass

    def save_periodic(self, frame):
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
            self.queue.put_nowait(('periodic', (frame, timestamp)))
        except queue.Full:
            pass

    def save_confirmed(self, raw_frame, debug_frame, side, pose_type):
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            prefix = f"{timestamp}_{side}_{pose_type}"
            self.queue.put_nowait(('confirmed', (raw_frame, debug_frame, prefix)))
        except queue.Full:
            pass

    def stop(self):
        self.stopped = True


def _json_default(o):
    """json.dump fallback for numpy scalars/arrays."""
    if hasattr(o, 'tolist'):
        return o.tolist()
    return str(o)


SKELETON_EDGES = [(5, 6), (5, 7), (7, 9), (6, 8), (8, 10), (5, 11), (6, 12), (11, 12),
                  (11, 13), (13, 15), (12, 14), (14, 16), (0, 5), (0, 6)]


def annotate_pose_record(rec, rel):
    """Draws a PoseEventLogger frame record: net line, every person's skeleton, and the T-pose checks they failed."""
    img = rec['image'].copy()
    oy = rec['crop_top']  # keypoints are in crop coordinates
    cv.line(img, (rec['net_x_px'], 0), (rec['net_x_px'], img.shape[0]), (0, 255, 255), 1)
    header = (f"{rec['time']}  frame {rel:+d}  loop {rec['loop_ms']}ms  "
              f"T-window L{''.join('1' if v else '0' for v in rec['tpose_window']['LEFT'])} "
              f"R{''.join('1' if v else '0' for v in rec['tpose_window']['RIGHT'])}")
    cv.putText(img, header, (8, 22), cv.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4)
    cv.putText(img, header, (8, 22), cv.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
    for p in rec['people']:
        k = p['kps']
        color = (0, 255, 0) if p['tpose'] else ((0, 165, 255) if p['arms_spread'] else (160, 160, 160))
        for a, b in SKELETON_EDGES:
            if k[a][2] >= 0.10 and k[b][2] >= 0.10:
                cv.line(img, (int(k[a][0]), int(k[a][1]) + oy), (int(k[b][0]), int(k[b][1]) + oy), color, 2)
        for x, y, c in k:
            if c >= 0.10:
                cv.circle(img, (int(x), int(y) + oy), 3, color, -1)
        label = f"{p['side'][0]} x={p['x']:.2f} " + ('T-POSE' if p['tpose'] else ','.join(p['fails']))
        if p['cobra']:
            label += ' COBRA'
        m = p['metrics']
        if m.get('swapped_lr'):
            label += ' [L/R swapped]'
        if m.get('projected_wrist'):
            label += f" [wrist est: {m['projected_wrist']}]"
        detail = (f"conf{m.get('min_conf')} sw{m.get('shoulder_w')} tilt{m.get('tilt_deg')} "
                  f"yoff{m.get('y_off_max_over_tol')} spine{m.get('arm_spine_deg')} "
                  f"span{m.get('wingspan_ratio')}/{m.get('wingspan_min')} elb{m.get('elbow_deg')}")
        tx = int(max(0, min(img.shape[1] - 420, k[6][0] - 60)))
        ty = int(max(40, min(img.shape[0] - 30, k[5][1] + oy - 30)))
        for i, text in enumerate((label, detail)):
            cv.putText(img, text, (tx, ty + 16 * i), cv.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3)
            cv.putText(img, text, (tx, ty + 16 * i), cv.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
    return img


class PoseEventLogger:
    """
    T-pose tuning data:
    - Keeps the last EVENT_PRE_FRAMES processed frames (raw image + every attributed person's keypoints
      and T-pose check results). When a point or cobra is confirmed, those frames plus the next
      EVENT_POST_FRAMES are written to FieldCaptures/PoseEvents/<time>_<side>_<type>/ as annotated
      JPEGs plus frames.json, so you can see how long the pose was held and which checks failed.
    - Every frame where someone has their arms spread (joint order passes) is appended to
      PoseEvents/tpose_candidates.jsonl, including near misses that never scored.
    The pre-trigger frames live only in RAM: nothing is written to the SD card unless a pose is confirmed.
    Images are referenced, not copied (raw_copy is a fresh array every loop); ~2.7 MB per frame.
    Disable everything with POSE_EVENT_LOGGING = False once tuning is finished.
    """
    def __init__(self, saver):
        self.saver = saver
        self.history = collections.deque(maxlen=EVENT_PRE_FRAMES + 1)   # + the trigger frame itself
        self.pending = []
        self.candidate_log = os.path.join(POSE_EVENTS_DIR, 'tpose_candidates.jsonl')

    def add_frame(self, rec):
        if not POSE_EVENT_LOGGING:
            return
        self.history.append(rec)
        for ev in self.pending:
            ev['frames'].append(rec)
            ev['post_left'] -= 1
        for ev in [e for e in self.pending if e['post_left'] <= 0]:
            self.saver.save_event(ev['name'], ev['frames'], ev['trigger_no'])
        self.pending = [e for e in self.pending if e['post_left'] > 0]

        for p in rec['people']:
            if p['arms_spread']:
                line = {'date': rec['date'], 'time': rec['time'], 'frame_no': rec['frame_no'],
                        'side': p['side'], 'x': round(p['x'], 3), 'tpose': p['tpose'],
                        'fails': p['fails'], 'metrics': p['metrics']}
                self.saver.append_jsonl(self.candidate_log, json.dumps(line, default=_json_default))

    def trigger(self, side, kind):
        """Call after add_frame() for the frame on which the point/cobra was confirmed."""
        if not POSE_EVENT_LOGGING or not self.history:
            return
        rec = self.history[-1]
        name = f"{self.saver.session_tag}_{rec['date']}_{rec['time'].replace(':', '').replace('.', '_')}_{side}_{kind}"
        self.pending.append({'name': name, 'frames': list(self.history),
                             'post_left': EVENT_POST_FRAMES, 'trigger_no': rec['frame_no']})


def run_inference_half(interpreter, input_size, half_frame):
    """Runs MoveNet MultiPose inference on a half-frame (capacity up to 6 players per side)."""
    ih, iw, _ = half_frame.shape
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    input_img = cv.resize(half_frame, (input_size[1], input_size[0]), interpolation=cv.INTER_LINEAR)
    input_img = cv.cvtColor(input_img, cv.COLOR_BGR2RGB)
    input_img = np.expand_dims(input_img, axis=0)

    if input_details[0]['dtype'] == np.uint8:
        input_tensor = input_img.astype(np.uint8)
    else:
        input_tensor = input_img.astype(np.float32)

    interpreter.set_tensor(input_details[0]['index'], input_tensor)
    interpreter.invoke()

    raw_output = interpreter.get_tensor(output_details[0]['index'])
    if raw_output.ndim == 3: people = raw_output[0]
    elif raw_output.ndim == 2: people = raw_output
    elif raw_output.ndim == 1: people = np.expand_dims(raw_output, axis=0)
    else: return []

    parsed = []
    for p in people:
        if len(p) < 56: continue
        kps = p[:51].reshape((17, 3))
        ymin, xmin, ymax, xmax, score = p[51:]
        if score < 0.18: continue
        # Discard only microscopic background noise (area < 0.008)
        if (ymax - ymin) * (xmax - xmin) < 0.008: continue

        parsed.append({
            'keypoints': kps,
            'bbox': [int(xmin * iw), int(ymin * ih), int(xmax * iw), int(ymax * ih)],
            'score': float(score)
        })
    return parsed


# Phone switch (see pi/scoreboard_link.py): while this file exists, detections are still found, logged and
# captured (useful for reviewing false positives) but no score pulse is sent to the Arduino. /dev/shm is cleared
# at boot, so detection starts enabled.
TPOSE_DISABLED_FILE = os.environ.get('SCOREBOARD_TPOSE_FLAG', '/dev/shm/scoreboard_tpose_disabled')


def pulse_pin(pin):
    if os.path.exists(TPOSE_DISABLED_FILE):
        print("[GESTURES OFF] detection confirmed, score pulse suppressed (phone switch)", flush=True)
        return
    pin.value = 1
    time.sleep(0.05)
    pin.value = 0


def main():
    print("=" * 65)
    print("Starting 12-Player Volleyball Scoreboard System (Dual-Half Pass)")
    print(f"Model: {MODEL_PATH} | Shape: {INPUT_SIZE} | Threads: {NUM_THREADS}")
    print(f"T-Pose Hold: {POSE_HOLD_FRAMES} frames | Cobra Hold: {COBRA_HOLD_SECONDS}s")
    print("=" * 65)

    interpreter = tflite.Interpreter(model_path=MODEL_PATH, num_threads=NUM_THREADS)
    try:
        input_details = interpreter.get_input_details()
        interpreter.resize_tensor_input(input_details[0]['index'], [1, INPUT_SIZE[0], INPUT_SIZE[1], 3])
    except Exception:
        pass
    interpreter.allocate_tensors()

    video_src = 0
    if len(sys.argv) > 1 and not sys.argv[1].startswith('-'):
        video_src = sys.argv[1]
    vs = CourtCameraStream(src=video_src, width=1280, height=720).start()
    # (no warm-up sleep: the main loop simply waits until the camera delivers its first frame)

    calibrator = NetCenterCalibrator(initial_center=0.50)
    keystone = KeystoneEstimator()
    capture_saver = AsyncCaptureSaver()

    # T-pose confirms when seen in POSE_HOLD_FRAMES of the last POSE_WINDOW_FRAMES processed frames
    tpose_window = {s: collections.deque(maxlen=POSE_WINDOW_FRAMES) for s in ('LEFT', 'RIGHT')}
    pose_logger = PoseEventLogger(capture_saver)
    frame_no = 0
    cobra_start_time = {
        'LEFT': 0.0,
        'RIGHT': 0.0
    }
    # A gesture must be released before it can score again, so one long hold never scores twice
    armed = {
        'LEFT': {'tpose': True, 'cobra': True},
        'RIGHT': {'tpose': True, 'cobra': True}
    }

    left_cooldown = 0.0
    right_cooldown = 0.0
    heartbeat = HeartbeatThread(heartbeatPin, HEARTBEAT_PERIOD,
                                ArduinoHello(os.environ.get('SCOREBOARD_UART', '/dev/ttyAMA1'))).start()
    last_periodic_save_time = time.monotonic()
    last_oled_update_time = 0.0
    oled_awake_until = time.monotonic() + OLED_BOOT_SECONDS
    oled_lit = False
    last_point_time = {'LEFT': -1e9, 'RIGHT': -1e9}  # for the OLED 'T-Pose!' label
    power_button = PowerButtonMonitor(powerOffButtonPin, POWER_HOLD_SECONDS).start() if IS_RPI else None

    fps_start = time.monotonic()
    frame_count = 0
    fps = 0.0
    status_start = time.monotonic()
    status_loops = 0
    watchdog = MainLoopWatchdog(MAIN_LOOP_STALL_SECONDS).start()

    while True:
        try:
            watchdog.tick()
            loop_start = time.monotonic()
            frame = vs.read()
            if frame is None:
                # No live camera frames: skip processing (the heartbeat stops, so the Arduino reports
                # the Pi disconnected) but keep the power button working
                if power_button is not None and power_button.shutdown_requested:
                    shutdown_pi(vs)
                    break
                time.sleep(0.05)
                continue

            raw_copy = frame.copy()
            h, w, _ = frame.shape

            # Gentle vertical crop (preserves head/wrist room for close players)
            crop_top = int(h * CROP_TOP_FRACTION)
            frame = frame[crop_top:int(h * CROP_BOTTOM_FRACTION), :]
            frame_no += 1
            ih, iw, _ = frame.shape
            t = time.monotonic()

            # Cooldown management
            if left_cooldown > 0 and t > left_cooldown: left_cooldown = 0.0
            if right_cooldown > 0 and t > right_cooldown: right_cooldown = 0.0

            # Dynamic net split with 12% overlap margin:
            # Outstretched arms of players standing 4 ft away are completely in-frame!
            split_x = int(calibrator.center_x * iw)
            max_x_left = min(iw, int((calibrator.center_x + OVERLAP_MARGIN) * iw))
            min_x_right = max(0, int((calibrator.center_x - OVERLAP_MARGIN) * iw))

            left_half = frame[:, :max_x_left]
            right_half = frame[:, min_x_right:]

            # Run inference on Left Half (Home Team - up to 6 players)
            left_people = run_inference_half(interpreter, INPUT_SIZE, left_half)
            # Run inference on Right Half (Away Team - up to 6 players)
            right_people = run_inference_half(interpreter, INPUT_SIZE, right_half)

            current_detections = {
                'LEFT': {'tpose': False, 'cobra': False},
                'RIGHT': {'tpose': False, 'cobra': False}
            }

            # Per-person processing for both halves. A player seen in the overlap zone is attributed to
            # the side their torso is on, so they are only evaluated once.
            side_xs = {'LEFT': [], 'RIGHT': []}
            frame_people = []   # for PoseEventLogger
            for side, people, x0, span in (('LEFT', left_people, 0, max_x_left),
                                           ('RIGHT', right_people, min_x_right, iw - min_x_right)):
                for p in people:
                    # Convert keypoints into TRUE ISOTROPIC PIXEL COORDINATES [x_px, y_px, score]
                    kps_px = np.zeros((17, 3), dtype=np.float32)
                    kps_px[:, 0] = x0 + p['keypoints'][:, 1] * span   # X in pixels [0, iw]
                    kps_px[:, 1] = p['keypoints'][:, 0] * ih          # Y in pixels [0, ih]
                    kps_px[:, 2] = p['keypoints'][:, 2]               # confidence score

                    # Torso centroid in pixels
                    sho_x = (kps_px[KP['left_shoulder']][0] + kps_px[KP['right_shoulder']][0]) / 2.0
                    sho_y = (kps_px[KP['left_shoulder']][1] + kps_px[KP['right_shoulder']][1]) / 2.0
                    has_h = (kps_px[KP['left_hip']][2] >= 0.15 and kps_px[KP['right_hip']][2] >= 0.15)
                    if has_h:
                        hip_x = (kps_px[KP['left_hip']][0] + kps_px[KP['right_hip']][0]) / 2.0
                        hip_y = (kps_px[KP['left_hip']][1] + kps_px[KP['right_hip']][1]) / 2.0
                        torso_x = (sho_x + hip_x) / 2.0
                        is_upright = (hip_y - sho_y) > (0.15 * ih)
                    else:
                        torso_x = sho_x
                        is_upright = True

                    # Team boundary attribution: torso must be on this half's side of the net
                    if (side == 'LEFT') == (torso_x >= split_x):
                        continue  # Player is physically on the other side (seen in the overlap)

                    if is_upright:
                        side_xs[side].append(torso_x / iw)
                        keystone.add(torso_x / iw, kps_px)

                    diag = {}
                    is_tpose = check_t_pose(kps_px, player_global_x=torso_x / iw,
                                            expected_lean_deg=keystone.lean_deg(torso_x / iw), frame_h=ih, diag=diag)
                    is_cobra = check_surrender_cobra(kps_px)
                    if is_tpose:
                        current_detections[side]['tpose'] = True
                    if is_cobra:
                        current_detections[side]['cobra'] = True
                    frame_people.append({
                        'side': side, 'x': float(torso_x / iw), 'score': round(p['score'], 2),
                        'tpose': is_tpose, 'cobra': is_cobra,
                        'arms_spread': 'joint_order' not in diag['fails'],
                        'fails': diag['fails'], 'metrics': diag['metrics'],
                        'kps': [[round(float(x), 1), round(float(y), 1), round(float(c), 2)] for x, y, c in kps_px],
                    })

                    b = p['bbox']
                    cv.rectangle(frame, (x0 + b[0], b[1]), (x0 + b[2], b[3]),
                                 (0, 255, 0) if side == 'LEFT' else (255, 0, 0), 2)

            # Feed quality frames to calibrator for drift tracking
            calibrator.add_quality_frame(side_xs['LEFT'], side_xs['RIGHT'])
            calibrator.update(t)
            keystone.update(t)

            # Update gesture state for both sides
            for s in ['LEFT', 'RIGHT']:
                # T-Pose: seen in POSE_HOLD_FRAMES of the last POSE_WINDOW_FRAMES frames. Re-armed only
                # after a full window without a T-pose (a real release, not a one-frame flicker).
                tpose_window[s].append(current_detections[s]['tpose'])
                if len(tpose_window[s]) == POSE_WINDOW_FRAMES and not any(tpose_window[s]):
                    armed[s]['tpose'] = True

                # Surrender Cobra: time-based >= 0.80s (prevents triggers on volleyball sets)
                if current_detections[s]['cobra']:
                    if cobra_start_time[s] == 0.0:
                        cobra_start_time[s] = t
                else:
                    cobra_start_time[s] = 0.0
                    armed[s]['cobra'] = True

            pose_logger.add_frame({
                'frame_no': frame_no, 'date': datetime.now().strftime('%Y%m%d'),
                'time': datetime.now().strftime('%H:%M:%S.%f')[:-3],
                'loop_ms': int(1000 * (time.monotonic() - loop_start)),
                'image': raw_copy, 'crop_top': crop_top, 'net_x_px': split_x,
                'tpose_window': {s: list(tpose_window[s]) for s in ('LEFT', 'RIGHT')},
                'people': frame_people,
            })

            # Pose Confirmation Logic
            for s in ['LEFT', 'RIGHT']:
                cooldown = left_cooldown if s == 'LEFT' else right_cooldown
                if cooldown == 0.0:
                    # Check confirmed T-Pose (+1 Point)
                    if armed[s]['tpose'] and sum(tpose_window[s]) >= POSE_HOLD_FRAMES:
                        print(f"\n[{datetime.now():%H:%M:%S}] >>> CONFIRMED POINT {s} "
                              f"({POSE_HOLD_FRAMES} of last {POSE_WINDOW_FRAMES} frames) <<<\n")
                        if s == 'LEFT':
                            pulse_pin(homeScorePin)
                            left_cooldown = t + SCORE_COOLDOWN
                            last_point_time['LEFT'] = t
                        else:
                            pulse_pin(awayScorePin)
                            right_cooldown = t + SCORE_COOLDOWN
                            last_point_time['RIGHT'] = t
                        tpose_window[s].clear()
                        armed[s]['tpose'] = False
                        oled_awake_until = max(oled_awake_until, t + OLED_EVENT_SECONDS)
                        calibrator.mark_first_point(t)
                        capture_saver.save_confirmed(raw_copy, frame, s, 'TPOSE')
                        pose_logger.trigger(s, 'TPOSE')

                    # Check confirmed Surrender Cobra (-1 Undo)
                    elif armed[s]['cobra'] and cobra_start_time[s] > 0.0 and (t - cobra_start_time[s]) >= COBRA_HOLD_SECONDS:
                        print(f"\n[{datetime.now():%H:%M:%S}] >>> CONFIRMED SUBTRACT {s} (held >= {COBRA_HOLD_SECONDS:.1f}s) <<<\n")
                        if s == 'LEFT':
                            pulse_pin(surrenderHomePin)
                            left_cooldown = t + SCORE_COOLDOWN
                        else:
                            pulse_pin(surrenderAwayPin)
                            right_cooldown = t + SCORE_COOLDOWN
                        cobra_start_time[s] = 0.0
                        armed[s]['cobra'] = False
                        oled_awake_until = max(oled_awake_until, t + OLED_EVENT_SECONDS)
                        calibrator.mark_first_point(t)
                        capture_saver.save_confirmed(raw_copy, frame, s, 'COBRA')
                        pose_logger.trigger(s, 'COBRA')

            # Periodic background frame capture (Async: every ~0.75s gives 4.5h in 5GB)
            if (t - last_periodic_save_time) >= SAVE_INTERVAL_SECONDS:
                last_periodic_save_time = t
                capture_saver.save_periodic(raw_copy)

            # Heartbeat: toggled at a steady period by HeartbeatThread while frames keep being processed
            heartbeat.alive(t)

            # Power button (polled on its own thread): short press wakes the OLED,
            # holding POWER_HOLD_SECONDS shuts down
            power_button_counter = 0
            button_held = False
            if power_button is not None:
                if power_button.shutdown_requested:
                    shutdown_pi(vs)
                    break
                power_button_counter = power_button.counter
                button_held = power_button.pressed_since > 0.0
                oled_awake_until = max(oled_awake_until, power_button.last_press_time + OLED_WAKE_SECONDS)

            # OLED: lit only while awake (boot aim-assist, after a point, or after a button press),
            # blanked otherwise to prevent burn-in. Refreshes every loop while the button is held so
            # the shutdown countdown is live.
            if HAS_OLED:
                if t < oled_awake_until:
                    refresh_due = (t - last_oled_update_time) >= 1.0 or button_held
                    if refresh_due:
                        last_oled_update_time = t
                        oled_frame = cv.resize(frame, (128, 128))
                        # Aim guides: grey ticks at the edges of the allowed net-line window,
                        # yellow line at the current net line
                        for edge in (calibrator.nominal_center - calibrator.max_drift,
                                     calibrator.nominal_center + calibrator.max_drift):
                            ex = int(edge * 128)
                            cv.line(oled_frame, (ex, 100), (ex, 127), (128, 128, 128), 1)
                        net_oled_x = int(calibrator.center_x * 128)
                        cv.line(oled_frame, (net_oled_x, 0), (net_oled_x, 128), (0, 255, 255), 1)
                        elapsed = time.monotonic() - loop_start
                        displayOLED(cv.cvtColor(oled_frame, cv.COLOR_BGR2RGB),
                                    elapsedTime=elapsed,
                                    powerButton=power_button_counter,
                                    leftT=(t - last_point_time['LEFT']) < OLED_EVENT_SECONDS,
                                    rightT=(t - last_point_time['RIGHT']) < OLED_EVENT_SECONDS)
                        oled_lit = True
                elif oled_lit:
                    clearDisplay()
                    oled_lit = False

            status_loops += 1
            if (t - status_start) >= STATUS_PRINT_SECONDS:
                temp_c, cpu_mhz = -1.0, -1
                try:
                    with open('/sys/class/thermal/thermal_zone0/temp') as f_:
                        temp_c = int(f_.read()) / 1000.0
                    with open('/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq') as f_:
                        cpu_mhz = int(f_.read()) // 1000
                except Exception:
                    pass
                loop_ms = 1000.0 * (t - status_start) / max(1, status_loops)
                print(f"[STATUS] loop={loop_ms:.0f}ms ({1000.0 / loop_ms:.1f} fps) threads={NUM_THREADS} "
                      f"net_center={calibrator.center_x:.3f} keystone={keystone.slope:.1f}deg/x{keystone.offset:+.1f} "
                      f"temp={temp_c:.1f}C cpu={cpu_mhz}MHz")
                status_start = t
                status_loops = 0

            frame_count += 1
            if (time.monotonic() - fps_start) >= 1.0:
                fps = frame_count / (time.monotonic() - fps_start)
                frame_count = 0
                fps_start = time.monotonic()

            if not IS_RPI:
                cv.line(frame, (split_x, 0), (split_x, ih), (255, 255, 0), 2)
                cv.putText(frame, f"FPS: {fps:.1f} | Center: {calibrator.center_x:.2f} (12-Player)", (15, 30),
                           cv.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)
                cv.imshow('Volleyball Scoreboard 12-Player', frame)
                if cv.waitKey(1) & 0xFF == 27:
                    break

        except Exception as loop_err:
            # Resilient top-level error handler: single corrupted frame never crashes the script
            print(f"[LOOP WARNING] Skipped error on frame: {loop_err}")
            time.sleep(0.01)

    vs.stop()
    capture_saver.stop()
    cv.destroyAllWindows()


if __name__ == '__main__':
    main()
