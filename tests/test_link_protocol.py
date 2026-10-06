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
import arduino_protocol as proto  # noqa: E402


class FakePort:
    """Stands in for a serial port: records (time, bytes) when used by ArduinoLink (time from its clock)."""
    def __init__(self):
        self.writes = []
        self.clock = None

    def write(self, data):
        if self.clock is not None:
            self.writes.append((self.clock(), data))
        return len(data)

    def close(self):
        pass

# the switch file the Pi service and the vision engine share (checked as source text below), and a test-only
# path so running the tests never touches a real Pi's switch
DEFAULT_SWITCH_PATH = '/dev/shm/scoreboard_tpose_disabled'
link.TPOSE_DISABLED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', '.tpose_disabled_test')
DEFAULT_STRICTNESS_PATH = '/home/pi/Documents/scoreboard_strictness.txt'
link.STRICTNESS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', '.strictness_test')

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
        # nothing received yet; T-pose detection is on by default, at the Standard strictness
        self.assertEqual(empty[1], link.FLAG_TPOSE_ON | (1 << link.FLAG_STRICT_SHIFT))

    def test_commands(self):
        line = link.build_command('TO,25')
        self.assertTrue(line.startswith('$C,TO,25*') and line.endswith(chr(13) + chr(10)))
        body, cs = line[1:].strip().split('*')
        x = 0
        for ch in body:
            x ^= ord(ch)
        self.assertEqual(int(cs, 16), x)
        self.assertIsNotNone(link.build_command('MODE,1'))
        for ok in ['SCORE,HU', 'SCORE,HD', 'SCORE,AU', 'SCORE,AD', 'TPOSE,0', 'TPOSE,1', 'SOUND,0', 'SOUND,1', 'SOUND,2',
                   'STRICT,0', 'STRICT,1', 'STRICT,2', 'STRICT,3']:
            self.assertIsNotNone(link.build_command(ok), ok)
        for bad in ['TO,30', 'MODE,2', 'HU', 'TO,25;MODE,1', '', 'mode,1', 'SCORE,HP', 'SCORE,H', 'SCORE,HU;SCORE,HU',
                    'TPOSE,2', 'SCORE,RS', 'RESET', 'SOUND,3', 'SOUND,-1', 'STRICT,4', 'STRICT,-1', 'STRICT,', 'STRICT,10',
                    'STRICT,1;STRICT,2']:
            self.assertIsNone(link.build_command(bad), bad)
        # the sketch must parse exactly these command names and values
        src = open(SKETCH, encoding='utf-8').read()
        self.assertIn('strcmp(name, "MODE") == 0 && (value == 0 || value == 1)', src)
        self.assertIn('strcmp(name, "TO") == 0 && (value == 15 || value == 21 || value == 25)', src)
        self.assertIn('strncmp(line, "C,", 2)', src)
        self.assertIn('strcmp(name, "SOUND") == 0 && value >= 0 && value <= 2', src)
        for code in ('HU', 'HD', 'AU', 'AD'):
            self.assertIn('strcmp(arg, "%s") == 0' % code, src)

    def test_pi_messages(self):
        # hello and gesture lines from the vision engine: checksummed, parsed by the sketch, never sendable by a phone
        self.assertEqual(proto.HELLO, b'$C,PI,2*68\r\n')
        for side in 'LR':
            for kind in 'PC':
                for event_id in (1, 17, 255):
                    line = proto.event_line(side, kind, event_id)
                    body, cs = line[1:].decode().strip().split('*')
                    self.assertEqual(body, 'C,PT,%s%s,%d' % (side, kind, event_id))
                    self.assertEqual(int(cs, 16), proto.checksum(body))
                    self.assertLessEqual(len(line) - 3, 31, 'must fit the sketch\'s 32-byte cmdBuf')
        for bad in [('X', 'P', 1), ('L', 'X', 1), ('L', 'P', 0), ('L', 'P', 256)]:
            with self.assertRaises(ValueError):
                proto.event_line(*bad)
        self.assertEqual(proto.next_id(255), 1)
        self.assertEqual(proto.next_id(1), 2)
        for cmd in ('PI,1', 'PI,2', 'PT,LP,1'):
            self.assertIsNone(link.build_command(cmd), 'phones must not be able to send %s' % cmd)
        src = open(SKETCH, encoding='utf-8').read()
        self.assertIn('strcmp(name, "PI") == 0 && (value == 1 || value == 2)', src)
        self.assertIn('strcmp(name, "PT") == 0', src)
        self.assertIn("bool left = arg[0] == 'L', right = arg[0] == 'R';", src)
        self.assertIn("bool point = arg[1] == 'P', cobra = arg[1] == 'C';", src)
        self.assertIn('#define CAMERA_LEFT_IS_AWAY 1', src)   # camera-left = away, as wired (Oct 2026)
        self.assertIn('if(piLinkUp && piVersion == 1)', src)   # GPIO pulses only from a version-1 engine
        self.assertIn('if(!piLinkUp || piVersion < 2)', src)   # serial gestures only from a version-2 engine
        self.assertIn('(int)piLinkUp,', src)                   # the phone's "Pi on" flag
        # the engine sends camera halves, through ArduinoLink, honoring the phone's T-pose switch
        engine = open(os.path.join(ROOT, 'pi', 'PoseEstimationJT_Optimized.py'), encoding='utf-8').read()
        self.assertIn("arduino.send_event(s[0], 'P')", engine)
        self.assertIn("arduino.send_event(s[0], 'C')", engine)
        self.assertIn('tpose_disabled_file=TPOSE_DISABLED_FILE', engine)
        self.assertNotIn('pulse_pin(', engine)

    def test_engine_link_timing(self):
        # ArduinoLink with a fake clock and port: hellos once a second while alive, 3 copies per gesture,
        # never two lines closer than MIN_GAP, nothing while the phone's T-pose switch is off
        t = [0.0]
        port = FakePort()
        port.clock = lambda: t[0]
        logs = []
        al = proto.ArduinoLink('fake', period=1.0, grace=1.5, opener=lambda: port, clock=lambda: t[0],
                               log=logs.append, tpose_disabled_file=link.TPOSE_DISABLED_FILE)
        al.alive()
        sent_at = None
        while t[0] < 4.0:
            if sent_at is None and t[0] >= 0.5:
                self.assertTrue(al.send_event('L', 'P'))
                sent_at = t[0]
            al.step()
            t[0] = round(t[0] + 0.01, 2)
        hellos = [w for w in port.writes if w[1] == proto.HELLO]
        events = [w for w in port.writes if w[1] != proto.HELLO]
        self.assertEqual([round(w[0], 2) for w in hellos], [0.0, 1.0], 'hello every second, stopping after the grace')
        self.assertEqual(len(events), 3)
        self.assertEqual(len(set(w[1] for w in events)), 1, 'all copies carry the same id')
        self.assertTrue(events[0][1].startswith(b'$C,PT,LP,'))
        times = [w[0] for w in port.writes]
        self.assertTrue(all(b - a >= proto.ArduinoLink.MIN_GAP - 1e-9 for a, b in zip(times, times[1:])))
        self.assertAlmostEqual(events[2][0] - events[0][0], 2 * proto.ArduinoLink.COPY_GAP, delta=0.02)
        # the phone's switch: detections are not sent at all
        open(link.TPOSE_DISABLED_FILE, 'w').close()
        try:
            self.assertFalse(al.send_event('R', 'C'))
            self.assertEqual(al.pending, [])
        finally:
            os.remove(link.TPOSE_DISABLED_FILE)

    def test_phone_command_copies(self):
        # the link service writes each phone command 3 times, paced; score taps carry an id; a newer setting
        # replaces the copies of an older one that are still waiting
        ls = link.LinkState()
        port = FakePort()
        self.assertEqual(ls.send_command('SCORE,HU'), 'UART not open')
        ls.serial = port
        self.assertIsNone(ls.send_command('SCORE,HU'))
        self.assertIsNone(ls.send_command('SCORE,HU'))     # a second tap: a different id
        self.assertIsNone(ls.send_command('MODE,1'))
        self.assertIsNone(ls.send_command('MODE,0'))       # changed its mind: MODE,1 must not arrive after it
        t = 0.0
        while t < 2.0:
            line = ls.pump(now=1e6 + t)
            if line is not None:
                port.writes.append((t, line))
            t = round(t + 0.01, 2)
        lines = [w[1] for w in port.writes if w[1] is not None]
        scores = [l for l in lines if l.startswith(b'$C,SCORE,HU,')]
        self.assertEqual(len(scores), 6)
        self.assertEqual(len(set(scores)), 2, 'two taps, two ids, three copies each')
        modes = [l for l in lines if l.startswith(b'$C,MODE,')]
        self.assertEqual(modes, [link.build_command('MODE,0').encode()] * 3)
        times = [w[0] for w in port.writes]
        self.assertTrue(all(b - a >= link.COMMAND_MIN_GAP - 1e-9 for a, b in zip(times, times[1:])))
        src = open(SKETCH, encoding='utf-8').read()
        self.assertIn('if(id > 0 && idSeen(recentScoreIds, id)) return;', src)

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
        self.assertIn('tpose_disabled_file=TPOSE_DISABLED_FILE', engine)
        with open(os.path.join(ROOT, 'pi', 'arduino_protocol.py'), encoding='utf-8') as f:
            self.assertIn('os.path.exists(self.tpose_disabled_file)', f.read())

    def test_detection_strictness(self):
        path = link.STRICTNESS_FILE

        def clean():
            for p in (path, path + '.tmp'):
                if os.path.exists(p):
                    os.remove(p)
        clean()
        state = link.parse_state_line(arduino_line(*CASES[1][1]))
        try:
            self.assertEqual(link.get_strictness(), 1, 'Standard until the phone chooses')
            self.assertEqual((link.pack_state(state, 0.5)[1] >> link.FLAG_STRICT_SHIFT) & 3, 1)
            ls = link.LinkState()
            for level in (0, 3, 2, 1):
                self.assertIsNone(ls.send_command('STRICT,%d' % level))     # handled on the Pi, no UART needed
                self.assertEqual(link.get_strictness(), level)
                for packet in (link.pack_state(state, 0.5), link.pack_state(None, 999)):
                    self.assertEqual((packet[1] >> link.FLAG_STRICT_SHIFT) & 3, level)
                    self.assertTrue(packet[1] & link.FLAG_TPOSE_ON, 'the other flag bits are untouched')
                    self.assertEqual(len(packet), 19)
            self.assertFalse(os.path.exists(path + '.tmp'), 'written atomically')
            self.assertEqual(open(path).read().strip(), '1')
            for junk in ('', 'x', '7', '-1'):                                # a damaged file means Standard
                with open(path, 'w') as f:
                    f.write(junk)
                self.assertEqual(link.get_strictness(), 1, repr(junk))
        finally:
            clean()
        # the service and the vision engine must agree on the file; the engine must read it and pass it on
        with open(os.path.join(ROOT, 'pi', 'scoreboard_link.py'), encoding='utf-8') as f:
            self.assertIn(DEFAULT_STRICTNESS_PATH, f.read())
        with open(os.path.join(ROOT, 'pi', 'PoseEstimationJT_Optimized.py'), encoding='utf-8') as f:
            engine = f.read()
        self.assertIn(DEFAULT_STRICTNESS_PATH, engine)
        self.assertIn('strictness = read_strictness(t)', engine)
        self.assertIn('limits = STRICTNESS_PRESETS[strictness]', engine)
        self.assertIn("tpose_confirmed(tpose_window[s], limits['hold'], limits['window'])", engine)

    def test_write_fixtures_for_js(self):
        def expect(args, strictness):
            return {'piOn': bool(args[4]), 'fresh': True, 'tposeOn': True, 'strictness': strictness, 'home': args[0],
                    'away': args[1], 'mode': args[2], 'scoreTo': args[3], 'homeColor': args[5], 'awayColor': args[6],
                    'digits': args[7], 'event': args[8], 'eventSeq': args[9], 'ageSeconds': 1.2,
                    'soundMode': args[10] if len(args) > 10 else 0,
                    'clockSecs': (args[11] if len(args) > 11 else (0, 0))[0],
                    'clockRunning': bool((args[11] if len(args) > 11 else (0, 0))[1])}
        if os.path.exists(link.STRICTNESS_FILE):
            os.remove(link.STRICTNESS_FILE)
        fixtures = []
        for name, args in CASES:
            state = link.parse_state_line(arduino_line(*args))
            packet = link.pack_state(state, 1.2)
            fixtures.append({'name': name, 'packet': packet.hex(), 'expect': expect(args, 1)})
        # one packet per detection strictness, made through the real command path
        try:
            for level in range(4):
                self.assertIsNone(link.LinkState().send_command('STRICT,%d' % level))
                state = link.parse_state_line(arduino_line(*CASES[1][1]))
                fixtures.append({'name': 'detection strictness %d' % level, 'packet': link.pack_state(state, 1.2).hex(),
                                 'expect': expect(CASES[1][1], level)})
        finally:
            for p in (link.STRICTNESS_FILE, link.STRICTNESS_FILE + '.tmp'):
                if os.path.exists(p):
                    os.remove(p)
        os.makedirs(os.path.dirname(FIXTURES), exist_ok=True)
        with open(FIXTURES, 'w', newline='\n') as f:
            json.dump(fixtures, f, indent=1)
            f.write('\n')


if __name__ == '__main__':
    unittest.main(verbosity=2)
