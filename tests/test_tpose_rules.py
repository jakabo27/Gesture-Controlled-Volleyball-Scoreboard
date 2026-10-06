"""
Rule tests for the T-pose check and its two-tier confirmation in pi/PoseEstimationJT_Optimized.py. Needs numpy.
Run from the repo root:

    python tests/test_tpose_rules.py

The engine imports the camera, TFLite and GPIO libraries, so the functions under test are pulled out of its source
with ast and run in a small namespace (same idea as the sketch checks in test_link_protocol.py).

The skeletons are synthetic: shoulders 80 px apart, arms 120 px long (1.5 shoulder widths), hanging `drop_deg` below
level (negative = raised). Numbers below were checked against real court frames in docs/engineering-log.md section 34.
"""
import ast
import math
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(ROOT, 'pi', 'PoseEstimationJT_Optimized.py')

NEEDED_FUNCS = {'calculate_angle_px', 'check_t_pose', 'tpose_confirmed'}
NEEDED_CONSTS = {'LIMB_CONF_THRESH', 'CLOSE_RANGE_SHOULDER_PX', 'CLOSE_RANGE_TOP_FRACTION', 'MIN_TPOSE_SHOULDER_PX', 'KP',
                 'POSE_HOLD_FRAMES', 'POSE_WINDOW_FRAMES', 'RELAXED_HOLD_FRAMES', 'RELAXED_WINDOW_FRAMES',
                 'RELAXED_BELOW_LEVEL_K', 'RELAXED_ARM_SPINE_MAX_DEG', 'RELAXED_ELBOW_MIN_DEG'}


def load_engine():
    src = open(ENGINE, encoding='utf-8').read()
    chunks = []
    for node in ast.parse(src).body:
        if isinstance(node, ast.FunctionDef) and node.name in NEEDED_FUNCS:
            chunks.append(ast.get_source_segment(src, node))
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in NEEDED_CONSTS for t in node.targets):
            chunks.append(ast.get_source_segment(src, node))
    ns = {'np': np}
    exec('\n\n'.join(chunks), ns)
    return ns


E = load_engine()
KP = E['KP']
FRAME_H = 648


def person(drop_deg=0.0, elbow_bend_deg=0.0, shoulder_w=80.0, arm_len=120.0, cx=640.0, conf=0.9):
    """Front-facing person, arms out to the sides, hanging drop_deg below level (negative = raised)."""
    k = np.zeros((17, 3), dtype=np.float32)
    k[:, 2] = conf
    half = shoulder_w / 2.0
    sy, hy = 300.0, 420.0
    k[KP['left_shoulder']][:2] = (cx + half, sy)          # the person's left = image right (no label swap needed)
    k[KP['right_shoulder']][:2] = (cx - half, sy)
    k[KP['left_hip']][:2] = (cx + half * 0.7, hy)
    k[KP['right_hip']][:2] = (cx - half * 0.7, hy)
    t = math.radians(drop_deg)
    bend = math.radians(elbow_bend_deg)
    for side, sh_name, el_name, wr_name in ((1.0, 'left_shoulder', 'left_elbow', 'left_wrist'),
                                            (-1.0, 'right_shoulder', 'right_elbow', 'right_wrist')):
        sx, sy_ = k[KP[sh_name]][:2]
        ex, ey = sx + side * 0.55 * arm_len * math.cos(t), sy_ + 0.55 * arm_len * math.sin(t)
        k[KP[el_name]][:2] = (ex, ey)
        # forearm continues the upper arm, optionally bent upwards by elbow_bend_deg
        ft = t - bend
        k[KP[wr_name]][:2] = (ex + side * 0.45 * arm_len * math.cos(ft), ey + 0.45 * arm_len * math.sin(ft))
    return k


def check(k):
    diag = {}
    ok = E['check_t_pose'](k, player_global_x=0.5, expected_lean_deg=0.0, frame_h=FRAME_H, diag=diag)
    return ok, diag['fails'], diag['metrics']


class TPoseRuleTest(unittest.TestCase):
    def test_level_arms_pass_the_strict_tier(self):
        ok, fails, m = check(person(0))
        self.assertTrue(ok, fails)
        self.assertFalse(m['relaxed_only'])

    def test_slightly_raised_arms_still_pass_strict(self):
        ok, fails, m = check(person(-10))
        self.assertTrue(ok, fails)
        self.assertFalse(m['relaxed_only'])

    def test_drooping_arms_pass_only_the_relaxed_tier(self):
        for drop in (15, 25):
            ok, fails, m = check(person(drop))
            self.assertTrue(ok, 'droop %d: %s' % (drop, fails))
            self.assertTrue(m['relaxed_only'], 'droop %d should need the longer hold' % drop)

    def test_arms_hanging_far_below_level_fail(self):
        ok, fails, _ = check(person(40))
        self.assertFalse(ok)
        self.assertIn('height_align', fails)

    def test_raised_arms_are_not_relaxed(self):
        # the relaxation is one-sided: hanging low is tolerated, rising above level is not
        for rise in (-15, -25):
            ok, fails, _ = check(person(rise))
            self.assertFalse(ok, 'arms %d deg above level must still fail' % -rise)
            self.assertIn('height_align', fails)

    def test_bent_elbows_fail(self):
        ok, fails, _ = check(person(0, elbow_bend_deg=70))
        self.assertFalse(ok)
        self.assertIn('elbow_straight', fails)

    def test_arms_down_fail(self):
        ok, _, _ = check(person(80))
        self.assertFalse(ok)

    def test_far_player_tolerance_floor(self):
        # small player (40 px shoulders): the 14 px floor applies, a clean T-pose still passes
        ok, fails, _ = check(person(0, shoulder_w=40.0, arm_len=60.0))
        self.assertTrue(ok, fails)


class ConfirmationTest(unittest.TestCase):
    """window values: 0 = no T-pose, 1 = relaxed-only pass, 2 = strict pass; newest last"""

    def test_strict_needs_two_of_the_last_three(self):
        c = E['tpose_confirmed']
        self.assertTrue(c([0, 2, 0, 2]))
        self.assertTrue(c([2, 2]))
        self.assertFalse(c([0, 0, 2, 0]))
        self.assertFalse(c([2, 0, 0, 2]))          # the first hit fell out of the 3-frame window

    def test_relaxed_needs_three_of_the_last_four(self):
        c = E['tpose_confirmed']
        self.assertFalse(c([0, 1, 1, 0]))          # two relaxed frames are not enough
        self.assertTrue(c([1, 1, 0, 1]))
        self.assertTrue(c([0, 1, 1, 1]))

    def test_mixed_tiers_count_towards_the_relaxed_rule(self):
        self.assertTrue(E['tpose_confirmed']([2, 0, 1, 1]))


if __name__ == '__main__':
    unittest.main(verbosity=2)
