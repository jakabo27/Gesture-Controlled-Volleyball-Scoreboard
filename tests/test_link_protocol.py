"""
Wire-contract tests for the Arduino -> Pi -> phone state link. Run from the repo root:

    python tests/test_link_protocol.py
    node tests/test_protocol.js        (uses the fixtures this test writes)

The Arduino side is checked by pulling the snprintf format string straight out of the sketch, so a change to
the line format there breaks this test instead of silently breaking the phone.
"""
import json
import os
import re
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'pi'))
import scoreboard_link as link  # noqa: E402

# the switch file the Pi service and the vision engine share (checked as source text below), and a test-only
# path so running the tests never touches a real Pi's switch
DEFAULT_SWITCH_PATH = '/dev/shm/scoreboard_tpose_disabled'
link.TPOSE_DISABLED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', '.tpose_disabled_test')

SKETCH = os.path.join(ROOT, 'arduino', 'ScoreboardVolleyballChangeWinning', 'ScoreboardVolleyballChangeWinning.ino')
FIXTURES = os.path.join(ROOT, 'tests', 'fixtures', 'state_packets.json')


def sketch_format():
    src = open(SKETCH, encoding='utf-8').read()
    m = re.search(r'snprintf\(body, sizeof\(body\), "([^"]+)"', src)
    assert m, 'state line format not found in the sketch'
    return m.group(1)


def arduino_line(home, away, mode, score_to, pi_on, home_color, away_color, digits, event, seq, sound=0, clock=(0, 0)):
    """Build a line exactly like sendStateIfDue() does."""
    body = sketch_format() % (home, away, mode, score_to, pi_on, home_color, away_color,
                              digits[0], digits[1], digits[2], digits[3], event, seq, sound, clock[0], clock[1])
    cs = 0
    for ch in body:
        cs ^= ord(ch)
    return '$%s*%02X\r\n' % (body, cs)


CASES = [
    # name, args to arduino_line
    ('boot', (0, 0, 0, 21, 0, 256, 256, [-1, 0, -1, 0], 'BOOT', 0)),
    ('mid game, hues', (14, 12, 0, 21, 1, 160, 0, [1, 4, 1, 2], 'HP', 37)),
    ('rainbow vs white, voice sound', (9, 23, 0, 25, 1, 257, 256, [-1, 9, 2, 3], 'AU', 255, 1)),
    ('tennis advantage, tones', (5, 4, 1, 21, 0, 96, 224, [10, 11, 0, 12], 'HU', 3, 2)),
    ('home wins, frozen clock', (21, 19, 0, 21, 1, 32, 192, [2, 1, 1, 9], 'HW', 120, 0, (1534, 0))),
    ('clock running', (3, 2, 0, 21, 1, 100, 100, [-1, 3, -1, 2], 'AU', 9, 0, (65535, 1))),
]


class LinkProtocolTest(unittest.TestCase):
    def test_sketch_fields_match_parser(self):
        # 16 conversions in the sketch's format = the 16 fields after 'S' the parser expects
        self.assertEqual(sketch_format().count('%'), 16)

    def test_round_trip(self):
        for name, args in CASES:
            line = arduino_line(*args)
            self.assertLessEqual(len(line), 63, '%s: line must fit the Mega TX buffer' % name)
            state = link.parse_state_line(line)
            self.assertIsNotNone(state, name)
            self.assertEqual((state['home'], state['away'], state['mode'], state['score_to']), args[:4], name)
            self.assertEqual(state['pi_on'], bool(args[4]), name)
            self.assertEqual((state['home_color'], state['away_color']), args[5:7], name)
            self.assertEqual(state['digits'], args[7], name)
            self.assertEqual((state['event'], state['event_seq']), args[8:10], name)
            self.assertEqual(state['sound_mode'], args[10] if len(args) > 10 else 0, name)
            self.assertEqual((link.pack_state(state, 0.4)[1] >> link.FLAG_SOUND_SHIFT) & 3, state['sound_mode'], name)
            packet = link.pack_state(state, 0.4)
            self.assertEqual(len(packet), 19)
            clock = args[11] if len(args) > 11 else (0, 0)
            self.assertEqual((state['clock_secs'], state['clock_running']), clock, name)
            self.assertEqual(struct.unpack('<H', packet[17:19])[0], clock[0], name)
            self.assertEqual(bool(packet[1] & link.FLAG_CLOCK_RUNNING), bool(clock[1]), name)
            self.assertLessEqual(len(packet), 20, 'must fit one notification at the default MTU')

    def test_rejects_corruption(self):
        good = arduino_line(*CASES[1][1])
        self.assertIsNotNone(link.parse_state_line(good))
        self.assertIsNone(link.parse_state_line(good.replace('14', '15', 1)))   # checksum mismatch
        self.assertIsNone(link.parse_state_line(good[5:]))                       # partial line
        self.assertIsNone(link.parse_state_line('\x00\xff$S,1*'))                # boot noise
        self.assertIsNone(link.parse_state_line('$S,1,2*03'))                    # wrong field count

    def test_stale_and_empty(self):
        state = link.parse_state_line(arduino_line(*CASES[1][1]))
        fresh = link.pack_state(state, 0.5)
        stale = link.pack_state(state, 10.0)
        self.assertTrue(fresh[1] & link.FLAG_FRESH)
        self.assertFalse(stale[1] & link.FLAG_FRESH)
        self.assertEqual(stale[16], 100)   # age byte (the clock follows it)
        empty = link.pack_state(None, 999)
        self.assertEqual(len(empty), 19)
        self.assertEqual(empty[1], link.FLAG_TPOSE_ON)   # nothing received yet; T-pose detection is on by default

    def test_commands(self):
        line = link.build_command('TO,25')
        self.assertTrue(line.startswith('$C,TO,25*') and line.endswith(chr(13) + chr(10)))
        body, cs = line[1:].strip().split('*')
        x = 0
        for ch in body:
            x ^= ord(ch)
        self.assertEqual(int(cs, 16), x)
        self.assertIsNotNone(link.build_command('MODE,1'))
        for ok in ['SCORE,HU', 'SCORE,HD', 'SCORE,AU', 'SCORE,AD', 'TPOSE,0', 'TPOSE,1', 'SOUND,0', 'SOUND,1', 'SOUND,2']:
            self.assertIsNotNone(link.build_command(ok), ok)
        for bad in ['TO,30', 'MODE,2', 'HU', 'TO,25;MODE,1', '', 'mode,1', 'SCORE,HP', 'SCORE,H', 'SCORE,HU;SCORE,HU',
                    'TPOSE,2', 'SCORE,RS', 'RESET', 'SOUND,3', 'SOUND,-1']:
            self.assertIsNone(link.build_command(bad), bad)
        # the sketch must parse exactly these command names and values
        src = open(SKETCH, encoding='utf-8').read()
        self.assertIn('strcmp(name, "MODE") == 0 && (value == 0 || value == 1)', src)
        self.assertIn('strcmp(name, "TO") == 0 && (value == 15 || value == 21 || value == 25)', src)
        self.assertIn('strncmp(line, "C,", 2)', src)
        self.assertIn('strcmp(name, "SOUND") == 0 && value >= 0 && value <= 2', src)
        for code in ('HU', 'HD', 'AU', 'AD'):
            self.assertIn('strcmp(arg, "%s") == 0' % code, src)

    def test_pi_handshake(self):
        # the vision engine's hello line must be checksummed correctly, the phone must not be able to send it,
        # and the sketch must gate every Pi score on it
        engine = open(os.path.join(ROOT, 'pi', 'PoseEstimationJT_Optimized.py'), encoding='utf-8').read()
        m = re.search(r"LINE = b'[$](C,PI,1)[*]([0-9A-F]{2})[\\]r[\\]n'", engine)
        self.assertIsNotNone(m, 'hello line not found in the engine')
        x = 0
        for ch in m.group(1):
            x ^= ord(ch)
        self.assertEqual(int(m.group(2), 16), x)
        self.assertIsNone(link.build_command('PI,1'), 'phones must not be able to send the handshake')
        src = open(SKETCH, encoding='utf-8').read()
        self.assertIn('strcmp(name, "PI") == 0 && value == 1', src)
        self.assertEqual(src.count('raspiOn && piHandshakeOk())'), 4 + 1)   # four Pi score checks + the phone-facing flag

    def test_tpose_switch(self):
        flag = link.TPOSE_DISABLED_FILE
        if os.path.exists(flag):
            os.remove(flag)
        state = link.parse_state_line(arduino_line(*CASES[1][1]))
        self.assertTrue(link.tpose_enabled(), 'enabled when the switch file is absent (every boot)')
        self.assertTrue(link.pack_state(state, 0.5)[1] & link.FLAG_TPOSE_ON)
        self.assertTrue(link.pack_state(None, 999)[1] & link.FLAG_TPOSE_ON)
        try:
            ls = link.LinkState()
            self.assertIsNone(ls.send_command('TPOSE,0'))     # handled on the Pi, no UART needed
            self.assertFalse(link.tpose_enabled())
            self.assertFalse(link.pack_state(state, 0.5)[1] & link.FLAG_TPOSE_ON)
            self.assertEqual(ls.send_command('TPOSE,1'), None)
            self.assertTrue(link.tpose_enabled())
            self.assertTrue(link.pack_state(state, 0.5)[1] & link.FLAG_TPOSE_ON)
        finally:
            if os.path.exists(flag):
                os.remove(flag)
        # the service and the vision engine must agree on the switch file, and the engine must honor it
        with open(os.path.join(ROOT, 'pi', 'scoreboard_link.py'), encoding='utf-8') as f:
            self.assertIn(DEFAULT_SWITCH_PATH, f.read())
        with open(os.path.join(ROOT, 'pi', 'PoseEstimationJT_Optimized.py'), encoding='utf-8') as f:
            engine = f.read()
        self.assertIn(DEFAULT_SWITCH_PATH, engine)
        self.assertIn('if os.path.exists(TPOSE_DISABLED_FILE):', engine)

    def test_write_fixtures_for_js(self):
        fixtures = []
        for name, args in CASES:
            state = link.parse_state_line(arduino_line(*args))
            packet = link.pack_state(state, 1.2)
            fixtures.append({
                'name': name, 'packet': packet.hex(),
                'expect': {'piOn': bool(args[4]), 'fresh': True, 'tposeOn': True, 'home': args[0], 'away': args[1],
                           'mode': args[2], 'scoreTo': args[3], 'homeColor': args[5], 'awayColor': args[6],
                           'digits': args[7], 'event': args[8], 'eventSeq': args[9], 'ageSeconds': 1.2,
                           'soundMode': args[10] if len(args) > 10 else 0,
                           'clockSecs': (args[11] if len(args) > 11 else (0, 0))[0],
                           'clockRunning': bool((args[11] if len(args) > 11 else (0, 0))[1])},
            })
        os.makedirs(os.path.dirname(FIXTURES), exist_ok=True)
        with open(FIXTURES, 'w', newline='\n') as f:
            json.dump(fixtures, f, indent=1)
            f.write('\n')


if __name__ == '__main__':
    unittest.main(verbosity=2)
