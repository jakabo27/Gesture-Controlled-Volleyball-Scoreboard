"""
Tests for the optical net-pole locator (pi/net_pole.py) and how the engine's NetCenterCalibrator follows it.
Needs numpy and OpenCV. Run from the repo root:

    python tests/test_net_pole.py

Synthetic scenes (a busy roof with a smooth grey column) cover the shapes and the failures; two real crops from the Oct 5
indoor session (roof, lights and the pole only, nobody in them) check the real thing: tests/fixtures/pole_early.jpg
(pole at 0.575, narrow) and pole_late.jpg (pole at 0.493, twice as wide).
"""
import ast
import os
import sys
import unittest

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'pi'))
import net_pole  # noqa: E402

FIXTURES = os.path.join(ROOT, 'tests', 'fixtures')
ENGINE = os.path.join(ROOT, 'pi', 'PoseEstimationJT_Optimized.py')


def scene(pole_x=None, pole_w=0.04, seed=0, w=1280, h=720, occlude=()):
    """A busy roof (random panels, dark beams, diagonal braces, lights, noise) with an optional smooth grey pole
    running top to bottom. occlude: [(y0, y1)] row ranges (fractions) covered by a person-like block in front of it."""
    rng = np.random.default_rng(seed)
    img = np.full((h, w, 3), 185, np.uint8)
    for _ in range(260):
        x, y = int(rng.integers(0, w - 40)), int(rng.integers(0, h - 20))
        cw, ch = int(rng.integers(20, 220)), int(rng.integers(8, 70))
        g = int(rng.integers(90, 235))
        cv2.rectangle(img, (x, y), (x + cw, y + ch), (g, g, min(255, g + 8)), -1)
    for y in range(20, h, 38):
        cv2.line(img, (0, y), (w, y + int(rng.integers(-6, 7))), (40, 40, 45), int(rng.integers(2, 6)))
    for _ in range(40):
        cv2.line(img, (int(rng.integers(0, w)), int(rng.integers(0, h))), (int(rng.integers(0, w)), int(rng.integers(0, h))),
                 (60, 60, 60), 2)
    for _ in range(25):
        cv2.circle(img, (int(rng.integers(0, w)), int(rng.integers(0, h // 2))), int(rng.integers(8, 25)), (255, 255, 255), -1)
    img = cv2.add(img, rng.integers(0, 14, img.shape, dtype=np.uint8))
    if pole_x is not None:
        x0, x1 = int((pole_x - pole_w / 2) * w), int((pole_x + pole_w / 2) * w)
        shade = np.linspace(150, 172, x1 - x0).astype(np.uint8)            # a cylinder is a little darker on one side
        img[:, x0:x1] = shade[None, :, None]
        cv2.line(img, (x0, 0), (x0, h), (95, 95, 95), 2)
        cv2.line(img, (x1, 0), (x1, h), (95, 95, 95), 2)
    for y0, y1 in occlude:
        cv2.rectangle(img, (int(w * 0.40), int(h * y0)), (int(w * 0.70), int(h * y1)), (40, 60, 160), -1)
    return img


class LocatorTest(unittest.TestCase):
    def test_finds_poles_of_every_width_and_position(self):
        for x in (0.46, 0.50, 0.535, 0.575):
            for width in (0.03, 0.05, 0.08):
                r = net_pole.locate_pole(scene(x, width, seed=int(x * 1000) + int(width * 100)))
                self.assertIsNotNone(r, 'pole at %.3f, width %.2f not found' % (x, width))
                self.assertAlmostEqual(r['x'], x, delta=0.012, msg='pole at %.3f, width %.2f' % (x, width))
                self.assertAlmostEqual(r['width'], width, delta=0.02)

    def test_no_pole_means_no_detection(self):
        for seed in range(8):
            self.assertIsNone(net_pole.locate_pole(scene(None, seed=seed)), 'seed %d' % seed)

    def test_a_person_in_front_of_one_band_does_not_matter(self):
        r = net_pole.locate_pole(scene(0.53, 0.04, seed=3, occlude=[(0.14, 0.27)]))
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r['x'], 0.53, delta=0.012)

    def test_a_pole_hidden_over_most_of_its_height_is_missed_not_misplaced(self):
        r = net_pole.locate_pole(scene(0.53, 0.04, seed=4, occlude=[(0.0, 0.60)]))
        self.assertTrue(r is None or abs(r['x'] - 0.53) < 0.012, r)

    def test_a_flat_wall_is_not_a_pole(self):
        img = scene(None, seed=5)
        img[:, 560:740] = 200                      # a wide smooth panel (14 % of the width): wider than any pole
        self.assertIsNone(net_pole.locate_pole(img))

    def test_works_at_other_resolutions(self):
        img = cv2.resize(scene(0.52, 0.05, seed=6), (640, 360), interpolation=cv2.INTER_AREA)
        r = net_pole.locate_pole(img)
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r['x'], 0.52, delta=0.02)

    def test_real_frames(self):
        for name, x, width in (('pole_early.jpg', 0.575, 0.025), ('pole_late.jpg', 0.493, 0.065)):
            img = cv2.imread(os.path.join(FIXTURES, name))
            self.assertIsNotNone(img, name)
            r = net_pole.locate_pole(img)
            self.assertIsNotNone(r, name)
            self.assertAlmostEqual(r['x'], x, delta=0.01, msg=name)
            self.assertAlmostEqual(r['width'], width, delta=0.015, msg=name)


class TrackerTest(unittest.TestCase):
    """NetPoleTracker turns single detections into a net line: confirmed by agreement, held when the pole is hidden."""

    def tracker(self, readings):
        """readings: list of x values (or None) returned by successive locate() calls"""
        it = iter(readings)
        tr = net_pole.NetPoleTracker(locate=lambda frame: (lambda x: None if x is None else {'x': x, 'width': 0.04})(next(it)))
        return tr

    def run_all(self, tr, n, dt=3.0):
        out = []
        for i in range(n):
            out.append(tr.update(i * dt, None))
        return out

    def test_locks_after_three_agreeing_detections(self):
        out = self.run_all(self.tracker([0.531, 0.532, 0.531, 0.531]), 4)
        self.assertEqual(out[:2], [None, None])
        self.assertAlmostEqual(out[2], 0.531, delta=0.002)
        self.assertIsNone(out[3], 'already locked there: announced once')

    def test_jitter_never_locks(self):
        out = self.run_all(self.tracker([0.50, 0.53, 0.50, 0.55, 0.51, 0.54]), 6)
        self.assertEqual(out, [None] * 6)

    def test_checks_are_throttled(self):
        calls = []
        tr = net_pole.NetPoleTracker(locate=lambda f: calls.append(1) or {'x': 0.5, 'width': 0.04})
        for t in (0.0, 0.5, 1.0, 2.9, 3.0, 4.0, 6.0):
            tr.update(t, None)
        self.assertEqual(len(calls), 3)            # at 0, 3 and 6 s

    def test_hidden_pole_keeps_the_last_lock(self):
        tr = self.tracker([0.52, 0.52, 0.52, None, None, None, 0.52, 0.52])
        out = self.run_all(tr, 8)
        self.assertAlmostEqual(out[2], 0.52, delta=0.002)
        self.assertEqual(out[3:], [None] * 5)
        self.assertAlmostEqual(tr.x, 0.52, delta=0.002)

    def test_a_reaimed_camera_relocks_after_three_new_readings(self):
        out = self.run_all(self.tracker([0.575] * 3 + [0.494] * 3), 6)
        self.assertAlmostEqual(out[2], 0.575, delta=0.002)
        self.assertEqual(out[3:5], [None, None])
        self.assertAlmostEqual(out[5], 0.494, delta=0.002)

    def test_one_stray_reading_does_not_move_the_net(self):
        out = self.run_all(self.tracker([0.52, 0.52, 0.52, 0.45, 0.52, 0.52]), 6)
        self.assertAlmostEqual(out[2], 0.52, delta=0.002)
        self.assertEqual([o for o in out[3:] if o is not None], [])

    def test_readings_outside_the_sane_range_are_ignored(self):
        lo, hi = net_pole.LOCK_RANGE
        out = self.run_all(self.tracker([lo - 0.05] * 4 + [hi + 0.05] * 4), 8)
        self.assertEqual(out, [None] * 8)


class CalibratorLockTest(unittest.TestCase):
    """The engine's NetCenterCalibrator, pulled out of the engine source with ast."""

    @classmethod
    def setUpClass(cls):
        src = open(ENGINE, encoding='utf-8').read()
        chunks = []
        for node in ast.parse(src).body:
            if isinstance(node, ast.ClassDef) and node.name == 'NetCenterCalibrator':
                chunks.append(ast.get_source_segment(src, node))
            elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'MAX_CENTER_DRIFT' for t in node.targets):
                chunks.append(ast.get_source_segment(src, node))
        import time
        cls.ns = {'np': np, 'time': time}
        exec('\n\n'.join(chunks), cls.ns)

    def test_without_a_pole_the_players_move_it_but_only_a_little(self):
        c = self.ns['NetCenterCalibrator'](0.50)
        for _ in range(10):
            c.add_quality_frame([0.20, 0.25], [0.80, 0.85])
        c.update(c.last_calibration_time + 11.0)
        self.assertFalse(c.locked)
        self.assertLessEqual(abs(c.center_x - 0.50), 0.07 + 1e-9)

    def test_locking_to_the_pole_goes_beyond_the_old_clamp_and_stays(self):
        c = self.ns['NetCenterCalibrator'](0.50)
        c.lock_to_pole(0.575)
        self.assertTrue(c.locked)
        self.assertAlmostEqual(c.center_x, 0.575)
        for _ in range(10):                                         # the players' midpoint is 0.40: ignored while locked
            c.add_quality_frame([0.10, 0.20], [0.60, 0.70])
        c.update(c.last_calibration_time + 100.0)
        self.assertAlmostEqual(c.center_x, 0.575)
        c.lock_to_pole(0.494)                                       # camera re-aimed
        self.assertAlmostEqual(c.center_x, 0.494)

    def test_engine_uses_the_tracker_and_the_switch(self):
        src = open(ENGINE, encoding='utf-8').read()
        self.assertIn("NET_POLE_LOCK = os.environ.get('SCOREBOARD_NET_POLE', '1') != '0'", src)
        self.assertIn('pole_tracker.update(t, raw_copy)', src)
        self.assertIn('calibrator.lock_to_pole(new_pole)', src)


if __name__ == '__main__':
    unittest.main(verbosity=2)
