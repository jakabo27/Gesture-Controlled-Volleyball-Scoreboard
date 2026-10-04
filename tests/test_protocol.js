// Checks the page's packet decoder against packets built by pi/scoreboard_link.py, and the LED color
// math against known FastLED values. Run `python tests/test_link_protocol.py` first (it writes the fixtures).
//   node tests/test_protocol.js
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const P = require(path.join(__dirname, '..', 'web', 'protocol.js'));

let failures = 0;
function check(name, fn) {
  try { fn(); console.log('ok   ' + name); }
  catch (e) { failures++; console.log('FAIL ' + name + '\n     ' + e.message); }
}

const fixtures = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'state_packets.json'), 'utf8'));
for (const f of fixtures) {
  check('decode: ' + f.name, () => {
    const bytes = Uint8Array.from(Buffer.from(f.packet, 'hex'));
    assert.deepStrictEqual(P.decodeState(bytes), f.expect);
  });
}

check('FastLED rainbow anchors', () => {
  assert.deepStrictEqual(P.rainbowHue(0), [255, 0, 0]);      // red
  assert.deepStrictEqual(P.rainbowHue(32), [171, 85, 0]);    // orange
  assert.deepStrictEqual(P.rainbowHue(64), [171, 170, 0]);   // yellow (FastLED's boosted yellow)
  assert.deepStrictEqual(P.rainbowHue(96), [0, 255, 0]);     // green
  assert.deepStrictEqual(P.rainbowHue(128), [0, 171, 85]);   // aqua
  assert.deepStrictEqual(P.rainbowHue(160), [0, 0, 255]);    // blue
  assert.deepStrictEqual(P.rainbowHue(192), [85, 0, 171]);   // purple
  assert.deepStrictEqual(P.rainbowHue(224), [170, 0, 85]);   // pink
});

check('rainbow digit sweeps the whole wheel', () => {
  assert.strictEqual(P.rainbowPixelHue(0, 0), 0);
  assert.strictEqual(P.rainbowPixelHue(6, 8), 250);           // last LED of segment G: map(62, 0, 63, 0, 255)
  assert.deepStrictEqual(P.ledColor(P.COLOR_WHITE, 3, 4), [255, 255, 255]);
  assert.deepStrictEqual(P.ledColor(160, 0, 0), [0, 0, 255]);
  assert.deepStrictEqual(P.ledColor(0, 0, 0), [0, 255, 0]);     // sketch red shows green on the GRB strip
  assert.deepStrictEqual(P.ledColor(96, 0, 0), [255, 0, 0]);    // sketch green shows red
});

check('digit table has 16 glyphs of 7 segments', () => {
  assert.strictEqual(P.DIGIT_TABLE.length, 16);
  for (const g of P.DIGIT_TABLE) assert.strictEqual(g.length, 7);
});

check('digit table matches the sketch', () => {
  const sketch = fs.readFileSync(path.join(__dirname, '..', 'arduino', 'ScoreboardVolleyballChangeWinning',
    'ScoreboardVolleyballChangeWinning.ino'), 'utf8');
  const block = sketch.slice(sketch.indexOf('bool digitTable'), sketch.indexOf('};', sketch.indexOf('bool digitTable')));
  const rows = block.split('\n').filter(l => /^\s*\{[01]/.test(l))
    .map(l => l.match(/\{([^}]*)\}/)[1].split(',').map(Number));
  assert.deepStrictEqual(rows, P.DIGIT_TABLE);
});

check('phone commands match the Pi whitelist', () => {
  assert.strictEqual(P.commandText('TO', 25), 'TO,25');
  assert.strictEqual(P.commandText('MODE', 0), 'MODE,0');
  assert.throws(() => P.commandText('TO', 30));
  assert.strictEqual(P.commandText('SCORE', 'HU'), 'SCORE,HU');
  assert.strictEqual(P.commandText('TPOSE', 0), 'TPOSE,0');
  assert.throws(() => P.commandText('SCORE', 'HP'));
  assert.strictEqual(P.commandText('SOUND', 2), 'SOUND,2');
  assert.throws(() => P.commandText('SOUND', 3));
  assert.throws(() => P.commandText('TPOSE', 2));
  const pi = fs.readFileSync(path.join(__dirname, '..', 'pi', 'scoreboard_link.py'), 'utf8');
  assert.ok(pi.includes("COMMAND_RE = re.compile(r'^(MODE,[01]|TO,(15|21|25)|TPOSE,[01]|SOUND,[012]|SCORE,(HU|HD|AU|AD))$')"));
  assert.ok(pi.includes(P.COMMAND_CHAR_UUID));
  assert.ok(pi.includes("AUTH_TOKEN = '" + P.AUTH_TOKEN + "'"), 'page and Pi must agree on the hello token');
  assert.strictEqual(P.helloText(), 'HELLO,' + P.AUTH_TOKEN);
});

if (failures) { console.log(failures + ' failed'); process.exit(1); }
console.log('all passed');
