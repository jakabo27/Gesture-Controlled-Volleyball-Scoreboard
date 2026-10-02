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

SKETCH = os.path.join(ROOT, 'arduino', 'ScoreboardVolleyballChangeWinning', 'ScoreboardVolleyballChangeWinning.ino')
FIXTURES = os.path.join(ROOT, 'tests', 'fixtures', 'state_packets.json')


def sketch_format():
    src = open(SKETCH, encoding='utf-8').read()
    m = re.search(r'snprintf\(body, sizeof\(body\), "([^"]+)"', src)
    assert m, 'state line format not found in the sketch'
    return m.group(1)


def arduino_line(home, away, mode, score_to, pi_on, home_color, away_color, digits, event, seq):
    """Build a line exactly like sendStateIfDue() does."""
    body = sketch_format() % (home, away, mode, score_to, pi_on, home_color, away_color,
                              digits[0], digits[1], digits[2], digits[3], event, seq)
    cs = 0
    for ch in body:
        cs ^= ord(ch)
    return '$%s*%02X\r\n' % (body, cs)


CASES = [
    # name, args to arduino_line
    ('boot', (0, 0, 0, 21, 0, 256, 256, [-1, 0, -1, 0], 'BOOT', 0)),
    ('mid game, hues', (14, 12, 0, 21, 1, 160, 0, [1, 4, 1, 2], 'HP', 37)),
    ('rainbow vs white', (9, 23, 0, 25, 1, 257, 256, [-1, 9, 2, 3], 'AU', 255)),
    ('tennis advantage', (5, 4, 1, 21, 0, 96, 224, [10, 11, 0, 12], 'HU', 3)),
    ('home wins', (21, 19, 0, 21, 1, 32, 192, [2, 1, 1, 9], 'HW', 120)),
]


class LinkProtocolTest(unittest.TestCase):
    def test_sketch_fields_match_parser(self):
        # 13 conversions in the sketch's format = the 13 fields after 'S' the parser expects
        self.assertEqual(sketch_format().count('%'), 13)

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
            packet = link.pack_state(state, 0.4)
            self.assertEqual(len(packet), 17)
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
        self.assertEqual(stale[-1], 100)
        empty = link.pack_state(None, 999)
        self.assertEqual(len(empty), 17)
        self.assertEqual(empty[1], 0)

    def test_commands(self):
        line = link.build_command('TO,25')
        self.assertTrue(line.startswith('$C,TO,25*') and line.endswith(chr(13) + chr(10)))
        body, cs = line[1:].strip().split('*')
        x = 0
        for ch in body:
            x ^= ord(ch)
        self.assertEqual(int(cs, 16), x)
        self.assertIsNotNone(link.build_command('MODE,1'))
        for bad in ['TO,30', 'MODE,2', 'HU', 'TO,25;MODE,1', '', 'mode,1']:
            self.assertIsNone(link.build_command(bad), bad)
        # the sketch must parse exactly these command names and values
        src = open(SKETCH, encoding='utf-8').read()
        self.assertIn('strcmp(name, "MODE") == 0 && (value == 0 || value == 1)', src)
        self.assertIn('strcmp(name, "TO") == 0 && (value == 15 || value == 21 || value == 25)', src)
        self.assertIn('strncmp(line, "C,", 2)', src)

    def test_write_fixtures_for_js(self):
        fixtures = []
        for name, args in CASES:
            state = link.parse_state_line(arduino_line(*args))
            packet = link.pack_state(state, 1.2)
            fixtures.append({
                'name': name, 'packet': packet.hex(),
                'expect': {'piOn': bool(args[4]), 'fresh': True, 'home': args[0], 'away': args[1],
                           'mode': args[2], 'scoreTo': args[3], 'homeColor': args[5], 'awayColor': args[6],
                           'digits': args[7], 'event': args[8], 'eventSeq': args[9], 'ageSeconds': 1.2},
            })
        os.makedirs(os.path.dirname(FIXTURES), exist_ok=True)
        with open(FIXTURES, 'w', newline='\n') as f:
            json.dump(fixtures, f, indent=1)
            f.write('\n')


if __name__ == '__main__':
    unittest.main(verbosity=2)
