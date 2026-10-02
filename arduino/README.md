# Arduino Mega 2560: scoreboard controller

`ScoreboardVolleyballChangeWinning/ScoreboardVolleyballChangeWinning.ino` is the firmware that owns the score. It runs the display, sound and manual controls by itself. The Raspberry Pi is an optional input that can only add or remove points while its heartbeat is healthy.

## Pinout

| Pin | Connected to |
|---|---|
| 3 | WS2812B data (252 LEDs = 4 digits × 7 segments × 9 LEDs) |
| 5 | Speaker output (TMRpcm PWM audio → amplifier) |
| 7 / 6 | Home + / Home − buttons (to GND, internal pull-ups) |
| 12 / 11 | Away + / Away − buttons |
| 8 | Reset button |
| A0 / A1 / A2 | Slide pots: brightness, home color, away color |
| 20 / 21 (SDA / SCL) | 16×2 I²C LCD (address 0x27) |
| 40, 50–52 | SD card (CS on 40, hardware SPI) |
| 45 / 47 | From Pi: Home +1 / Away +1 |
| 42 / 43 | From Pi: Home −1 / Away −1 (cobra) |
| 46 | From Pi: heartbeat |
| 44 | From Pi: spare |
| 18 / 19 (TX1 / RX1) | State line to the Pi (phone display), 38400 baud. TX1 goes through a 10k/20k divider to the Pi's 3.3V RX |

## Controls

| Action | Result |
|---|---|
| + / − | Change that team's score (500ms repeat lockout) |
| Reset | 0–0 and re-arm the win celebration |
| Any 2 score buttons | Volleyball: cycle game-to **21 → 25 → 15** |
| Any 3 score buttons | Toggle voice clips / plain beeps |
| All 4 score buttons | Switch **volleyball ↔ tennis** scoring |
| Color slider at either end | White, or a rainbow across the digit |

In tennis mode the digits show 0 / 15 / 30 / 40, and deuce and advantage are spelled out with the extra glyphs in `digitTable` (`Ad`, `-`, `dE uc`). Winning by 2 at the game-to score plays a victory song once.

## How it trusts the Pi

* Every heartbeat edge is timed. The Pi counts as connected when the last periods agree within ±700ms and are longer than 75ms. The first edge after boot connects straight away. It takes **3 consecutive irregular periods**, or 4s of silence, to declare a disconnect.
* Pi pulses are ignored unless the Pi is connected, and are rate-limited to one change every 3s.
* Connect and disconnect are announced (`PiCon.wav` / `PiDis.wav`), so you know whether gestures are live.
* The heartbeat periods are **signed** `long`. An `unsigned long` version made `prev - range` wrap to ~4.29 billion for any period under 700ms, so the Pi always "disconnected" about 7s after connecting.

## State broadcast for the phone display

Once per change (at most every 100ms) and at least once a second, `sendStateIfDue()` writes one checksummed line on Serial1:

```
$S,<home>,<away>,<sportMode>,<scoreTo>,<piOn>,<homeColor>,<awayColor>,<d0>,<d1>,<d2>,<d3>,<event>,<eventSeq>*<XOR>
```

The fields are: the scores, the mode and game-to, whether the Pi is trusted, both team colors (FastLED hue, 256 white, 257 rainbow), the four glyphs `UpdateDisplay()` drew, and what caused the last change. The line is only written if the whole thing fits in the TX buffer, so with nothing connected (or a dead Pi) the scoreboard behaves exactly as before. The format is checked by [`tests/test_link_protocol.py`](../tests/test_link_protocol.py).

## SD card

The sketch plays 8.3-named WAV files from the SD card root: `PtHm`, `PtAwy`, `SurHo`, `SurAw`, `hUp1-3`, `hDown1-3`, `aUp1-3`, `aDown1-3`, `Reset`, `PiCon`, `PiDis`, `VBMode`, `TMode`, `WavMd`, `VBto15`, `VBto21`, `VBto25`, `Boot`, `Champ`, `allWin`.

Format: **16kHz, 8-bit unsigned, mono, plain 44-byte WAV header** (what TMRpcm expects). The audio isn't in this repo because the boot, champion and win clips are copyrighted music. If the SD card fails, the sketch falls back to `tone()` beeps and buzzer melodies.

[`tools/clean_wavs.py`](../tools/clean_wavs.py) cleans a folder of these clips. It trims dead air (point sounds used to start ~170ms late), gates the 8-bit hiss and normalizes every clip to the same peak. Copy it next to the WAVs and run it, and the results go to `SD_card_cleaned/`.

## Libraries

`FastLED`, `TMRpcm` (+ `SD`, `SPI`), `LCD_I2C`, `elapsedMillis`, `ResponsiveAnalogRead`. All of them are in the Arduino Library Manager.
