// Scoreboard BLE protocol + LED color math, shared by the page (app.js) and the tests (tests/).
// Must match pi/scoreboard_link.py (PACKET_FORMAT) and the Arduino sketch (digitTable, colors).
(function (root) {
  'use strict';

  const SERVICE_UUID = 'b3710001-1a78-4239-800f-cf4fa9544bbe';
  const STATE_CHAR_UUID = 'b3710002-1a78-4239-800f-cf4fa9544bbe';
  const COMMAND_CHAR_UUID = 'b3710003-1a78-4239-800f-cf4fa9544bbe';
  const DEVICE_NAME = 'Scoreboard';

  const COLOR_WHITE = 256;
  const COLOR_RAINBOW = 257;
  const EVENTS = ['', 'BOOT', 'HU', 'HD', 'AU', 'AD', 'HP', 'AP', 'HC', 'AC', 'RS', 'HW', 'AW', 'MD', 'GT', 'SM'];

  // digitTable from the Arduino sketch: segments A..G per glyph. On the scoreboard the segments are wired
  // A = lower left, B = upper left, C = top, D = upper right, E = middle, F = lower right, G = bottom.
  const DIGIT_TABLE = [
    [1, 1, 1, 1, 0, 1, 1], // 0
    [0, 0, 0, 1, 0, 1, 0], // 1
    [1, 0, 1, 1, 1, 0, 1], // 2
    [0, 0, 1, 1, 1, 1, 1], // 3
    [0, 1, 0, 1, 1, 1, 0], // 4
    [0, 1, 1, 0, 1, 1, 1], // 5
    [1, 1, 1, 0, 1, 1, 1], // 6
    [0, 0, 1, 1, 0, 1, 0], // 7
    [1, 1, 1, 1, 1, 1, 1], // 8
    [0, 1, 1, 1, 1, 1, 1], // 9
    [1, 1, 1, 1, 1, 1, 0], // 10 = A
    [1, 0, 0, 1, 1, 1, 1], // 11 = d
    [0, 0, 0, 0, 1, 0, 0], // 12 = -
    [1, 1, 1, 0, 1, 0, 1], // 13 = E
    [1, 0, 0, 0, 0, 1, 1], // 14 = u
    [1, 0, 0, 0, 1, 0, 1], // 15 = c
  ];

  // Settings the phone may change (the Pi forwards only these): sport mode and volleyball game-to.
  const COMMANDS = { MODE: [0, 1], TO: [15, 21, 25] };
  function commandText(name, value) {
    if (!COMMANDS[name] || !COMMANDS[name].includes(value)) throw new Error('not allowed: ' + name + ' ' + value);
    return `${name},${value}`;
  }

  // Decode the 17-byte state packet (DataView or Uint8Array).
  function decodeState(data) {
    const v = data instanceof DataView ? data : new DataView(data.buffer, data.byteOffset, data.byteLength);
    if (v.byteLength < 17) throw new Error('short packet: ' + v.byteLength + ' bytes');
    const version = v.getUint8(0);
    if (version !== 1) throw new Error('unknown packet version ' + version);
    const flags = v.getUint8(1);
    return {
      piOn: !!(flags & 0x01),
      fresh: !!(flags & 0x02),
      home: v.getUint8(2),
      away: v.getUint8(3),
      mode: v.getUint8(4),
      scoreTo: v.getUint8(5),
      homeColor: v.getUint16(6, true),
      awayColor: v.getUint16(8, true),
      digits: [v.getInt8(10), v.getInt8(11), v.getInt8(12), v.getInt8(13)],
      event: EVENTS[v.getUint8(14)] || '',
      eventSeq: v.getUint8(15),
      ageSeconds: v.getUint8(16) / 10,
    };
  }

  // FastLED scale8 (FASTLED_SCALE8_FIXED = 1, the default)
  function scale8(i, scale) {
    return ((i * (1 + scale)) >> 8) & 0xff;
  }

  // FastLED hsv2rgb_rainbow at full saturation and value: the exact color CHSV(hue, 255, 255) gives on the LEDs.
  function rainbowHue(hue) {
    hue &= 0xff;
    const offset8 = (hue & 0x1f) << 3;
    const third = scale8(offset8, 85);
    const twothirds = scale8(offset8, 170);
    let r, g, b;
    if (!(hue & 0x80)) {
      if (!(hue & 0x40)) {
        if (!(hue & 0x20)) { r = 255 - third; g = third; b = 0; }          // red -> orange
        else { r = 171; g = 85 + third; b = 0; }                         // orange -> yellow
      } else {
        if (!(hue & 0x20)) { r = 171 - twothirds; g = 170 + third; b = 0; } // yellow -> green
        else { r = 0; g = 255 - third; b = third; }                       // green -> aqua
      }
    } else {
      if (!(hue & 0x40)) {
        if (!(hue & 0x20)) { r = 0; g = 171 - twothirds; b = 85 + twothirds; } // aqua -> blue
        else { r = third; g = 0; b = 255 - third; }                          // blue -> purple
      } else {
        if (!(hue & 0x20)) { r = 85 + third; g = 0; b = 171 - third; }   // purple -> pink
        else { r = 170 + third; g = 0; b = 85 - third; }                 // pink -> red
      }
    }
    return [r, g, b];
  }

  // Arduino map() for the rainbow digits: CHSV(map(i*9 + pixel, 0, 63, 0, 255), 255, 255)
  function rainbowPixelHue(segment, pixel) {
    return Math.floor((segment * 9 + pixel) * 255 / 63);
  }

  // What the strip really shows for a FastLED color: the WS2812B strip is wired GRB but the sketch declares
  // NEOPIXEL (RGB order), so red and green are swapped on the LEDs. The phone copies what the LEDs show.
  function ledRgb(c) { return [c[1], c[0], c[2]]; }

  // Color of one LED of a digit: segment 0-6 (A-G), pixel 0-8 along the segment
  function ledColor(colorCode, segment, pixel) {
    if (colorCode === COLOR_WHITE || colorCode > COLOR_RAINBOW) return [255, 255, 255];
    if (colorCode === COLOR_RAINBOW) return ledRgb(rainbowHue(rainbowPixelHue(segment, pixel)));
    return ledRgb(rainbowHue(colorCode));
  }

  const api = {
    SERVICE_UUID, STATE_CHAR_UUID, COMMAND_CHAR_UUID, COMMANDS, commandText, DEVICE_NAME, COLOR_WHITE, COLOR_RAINBOW, EVENTS, DIGIT_TABLE,
    decodeState, rainbowHue, rainbowPixelHue, ledRgb, ledColor,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.ScoreboardProtocol = api;
})(this);
