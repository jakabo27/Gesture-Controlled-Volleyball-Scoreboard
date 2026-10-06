"""
Optical net-pole locator (engineering log section 20 and 36): finds the near net pole in the camera picture and tells the
vision engine where the net line is, instead of guessing it from where the players stand.

    locate_pole(frame_bgr) -> {'x': 0..1, 'width': fraction, 'score': 0..1, 'bands': n}  or None
    NetPoleTracker().update(t, frame_bgr) -> a newly locked pole x, or None

The pole is a plain grey column that runs through the whole upper picture, where everything around it (roof trusses,
lights) is busy. For each band of rows the locator looks for a run of columns that is SMOOTH along the vertical (almost
no up-down gradient), 2-12 % of the frame wide, with a strong vertical edge on both sides. Several row bands vote, so a
player in front of one band does not move the answer. The apparent width depends on how close the camera hangs to the
pole (about 3 % to 8 % in the Oct 5 frames). The camera is aimed by hand, and the pole sat anywhere from 0.49 to 0.575 of
the frame width in one indoor session.

Needs numpy and OpenCV (the engine already has both). Pure functions plus one small state class, so it is unit-tested
without a camera (tests/test_net_pole.py).
"""
import collections

import cv2 as cv
import numpy as np

ZONE = (0.36, 0.74)                  # where the pole may appear in the picture
BANDS = ((0.02, 0.17), (0.13, 0.28), (0.24, 0.39), (0.35, 0.50))   # rows (fractions of the height) that vote
WIDTH_RANGE = (0.020, 0.120)         # pole width as a fraction of the frame width
SMOOTH_FRACTION = 0.40               # a column is "smooth" when its vertical gradient is below this x the zone's median
MIN_EDGE = 0.40                      # fraction of rows with a strong vertical edge on each side of the run
MIN_BANDS = 3                        # bands that must agree ...
AGREE = 0.012                        # ... to within this much of the frame width

# NetPoleTracker: how a detection becomes the engine's net line
LOCK_RANGE = (0.40, 0.62)            # a pole outside this range is ignored (a net line there would be a mis-detection)
CHECK_SECONDS = 3.0                  # the locator runs this often (about 10-20 ms of work on a Pi 4)
CONFIRM = 3                          # consecutive detections that must agree before the net line moves
CONFIRM_SPREAD = 0.008               # ... to within this much of the frame width
MIN_CHANGE = 0.004                   # a new lock closer than this to the current one is not announced


def _band_pole(gray_small, y0, y1):
    h, w = gray_small.shape
    band = gray_small[int(y0 * h):int(y1 * h)]
    gx = np.abs(cv.Sobel(band, cv.CV_32F, 1, 0, ksize=3))
    gy = np.abs(cv.Sobel(band, cv.CV_32F, 0, 1, ksize=3))
    ey = cv.blur(gy.mean(axis=0).reshape(1, -1), (5, 1)).ravel()          # vertical-gradient energy per column
    thr = max(40.0, float(np.percentile(gx, 88)))
    strong = cv.dilate((gx >= thr).astype(np.uint8), np.ones((1, 5), np.uint8)).astype(bool)
    col = strong.mean(axis=0)                                              # fraction of rows with a vertical edge here
    lo, hi = int(ZONE[0] * w), int(ZONE[1] * w)
    wmin, wmax = max(4, int(WIDTH_RANGE[0] * w)), int(WIDTH_RANGE[1] * w)
    med = float(np.median(ey[lo:hi])) + 1e-6
    smooth = ey <= SMOOTH_FRACTION * med
    best = None
    x = lo
    while x < hi:
        if not smooth[x]:
            x += 1
            continue
        a = x
        while x < hi and smooth[x]:
            x += 1
        b = x                                                              # run [a, b)
        # the run may stop a few px short of the true edges (shading): grow it to the nearest strong edge columns
        left = max(range(max(lo, a - 6), a + 3), key=lambda c: col[c])
        right = max(range(max(a + 1, b - 3), min(w, b + 7)), key=lambda c: col[c])
        width = right - left
        if not (wmin <= width <= wmax):
            continue
        edge = min(col[left], col[right])
        if edge < MIN_EDGE:
            continue
        inner = float(ey[left + 2:right - 1].mean()) / med if right - left > 4 else 1.0
        s = edge * (1.0 - min(inner, 1.0))
        if best is None or s > best[0]:
            best = (s, (left + right) / 2.0 / w, width / w)
    return best


def locate_pole(frame_bgr):
    h, w = frame_bgr.shape[:2]
    small = cv.resize(cv.cvtColor(frame_bgr, cv.COLOR_BGR2GRAY), (w // 2, h // 2), interpolation=cv.INTER_AREA)
    small = cv.GaussianBlur(small, (3, 3), 0)
    found = [r for r in (_band_pole(small, y0, y1) for y0, y1 in BANDS) if r]
    if len(found) < MIN_BANDS:
        return None
    med = float(np.median([f[1] for f in found]))
    agree = [f for f in found if abs(f[1] - med) <= AGREE]
    if len(agree) < MIN_BANDS:
        return None
    return {'x': float(np.median([f[1] for f in agree])), 'width': float(np.median([f[2] for f in agree])),
            'score': float(np.mean([f[0] for f in agree])), 'bands': len(agree)}


class NetPoleTracker:
    """Turns single detections into a trustworthy net line.

    update(t, frame) looks for the pole at most every CHECK_SECONDS (t in seconds, any clock). A pole position is adopted
    when CONFIRM consecutive detections agree within CONFIRM_SPREAD and lie in LOCK_RANGE; the median is returned once per
    change. A frame without a clear pole (hidden behind a player, glare) is skipped: the last position is kept and the
    run of agreeing detections is not reset, but a detection that disagrees starts the run again (the camera was re-aimed).
    `locate` can be replaced in tests."""

    def __init__(self, locate=locate_pole):
        self.locate = locate
        self.x = None                                  # the adopted pole position, None until the first lock
        self.recent = collections.deque(maxlen=CONFIRM)
        self.last_check = -1e9
        self.checks = 0
        self.detections = 0

    def update(self, t, frame):
        if t - self.last_check < CHECK_SECONDS:
            return None
        self.last_check = t
        self.checks += 1
        r = self.locate(frame)
        if r is None or not (LOCK_RANGE[0] <= r['x'] <= LOCK_RANGE[1]):
            return None
        self.detections += 1
        if self.recent and abs(r['x'] - float(np.median(self.recent))) > CONFIRM_SPREAD:
            self.recent.clear()
        self.recent.append(r['x'])
        if len(self.recent) < CONFIRM:
            return None
        new = float(np.median(self.recent))
        if self.x is not None and abs(new - self.x) < MIN_CHANGE:
            return None
        self.x = new
        return new
