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
| + / − | Change that team's score (held: repeats every 500ms) |
| Reset | 0–0 and re-arm the win celebration |
| Any 2 score buttons together | Volleyball: cycle game-to **21 → 25 → 15** (announced) |
| Any 3 score buttons together | Toggle voice clips / plain beeps |
| All 4 score buttons together | Switch **volleyball ↔ tennis** (resets to 0–0) |
| Color slider at either end | White, or a rainbow across the digit |
| Phone page → Settings → Scoreboard | Sport and game-to, the same as the 4- and 2-button chords |

**How chords work:**
* A single press still scores instantly.
* If more buttons join, that first press is undone and the buttons count as a chord.
* The chord fires **while the buttons are still held**: immediately once all 4 are down, or 0.35s after the last button joins for 2 or 3. You hear the announcement then.
* After that, all score buttons are ignored until every one is released, so letting go can't trigger anything.
* The old version waited a fixed 400ms, let the first button score, and acted on the way out as buttons were released one by one. That's why chords used to be unreliable.

In tennis mode the digits show 0 / 15 / 30 / 40, and deuce and advantage are spelled out with the extra glyphs in `digitTable` (`Ad`, `-`, `dE uc`).

**Celebration:** winning by 2 at the game-to score plays a victory song once (re-armed by Reset or a sport change).
* It doesn't block: any score button, Reset or cobra stops it immediately and does its job.
* Fixing an accidental winning point is one press on −.
* A T-pose point during the song doesn't cut it off.

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

## Commands from the Pi (phone settings)

`serviceSerialCommands()` reads Serial1 RX (pin 19, from the Pi's pin 27 through 1k) without blocking. It accepts only two checksummed lines:

```
$C,MODE,<0|1>*<XOR>        sport: 0 volleyball, 1 tennis (resets the score, like the 4-button chord)
$C,TO,<15|21|25>*<XOR>     volleyball game-to
```

Anything else (boot noise, a half line, a wrong checksum) is ignored. The new setting shows up in the next state line, which is how the phone confirms it.

## Loudness

The firmware already drives the speaker as hard as it can without clipping, so the volume is limited by the clips and the amplifier.

* **How TMRpcm drives pin 5:** with `quality(1)` and 16kHz files, the PWM runs at 32kHz with **500 steps** of range. `setVolume(5)` doubles every 8-bit sample (0–255 → 0–510), so a full-scale clip spans the whole range. `setVolume(6)` would quadruple it and clip hard, so 5 is the maximum.
* **The original clips only reached 26–47% of full scale,** so the speaker got a quarter to half of the possible swing. `tools/clean_wavs.py` normalizes every clip to a peak of 120/127 (about 97% of the PWM range): **+3 to +7 dB** on the voice clips. `python tools/clean_wavs.py --loud <folder>` also applies look-ahead compression (same peak, quieter parts of each word lifted) for about **+2 to +4 dB more** on speech. Copy `SD_card_loud/*.wav` to the SD card.
* **Free +6 dB with a differential amp:** TMRpcm also outputs an *inverted* copy of the audio on OC3B = **pin 2**. If the amplifier has a differential (balanced) input, set `#define BRIDGED_AUDIO 1` and wire IN+ to pin 5, IN− to pin 2. That doubles the voltage swing. Don't do this with a single-ended amp whose input ground is its power ground (most PAM8403 boards): there, pin 2 would fight ground.
* **Things outside the firmware worth checking:**
  * The amp's own gain or volume pot.
  * The amp's supply voltage: the same amp on 12V gets much louder than on 5V.
  * An RC low-pass between pin 5 and the amp input (for example 1k + 10nF). This strips the 32kHz carrier, which otherwise eats amplifier headroom, so the amp gain can go higher before it clips.

## SD card

The sketch plays 8.3-named WAV files from the SD card root: `PtHm`, `PtAwy`, `SurHo`, `SurAw`, `hUp1-3`, `hDown1-3`, `aUp1-3`, `aDown1-3`, `Reset`, `PiCon`, `PiDis`, `VBMode`, `TMode`, `WavMd`, `VBto15`, `VBto21`, `VBto25`, `Boot`, `Champ`, `allWin`.

Format: **16kHz, 8-bit unsigned, mono, plain 44-byte WAV header** (what TMRpcm expects). The audio isn't in this repo because the boot, champion and win clips are copyrighted music. If the SD card fails, the sketch falls back to `tone()` beeps and buzzer melodies.

[`tools/clean_wavs.py`](../tools/clean_wavs.py) cleans a folder of these clips. It trims dead air (point sounds used to start ~170ms late), gates the 8-bit hiss and normalizes every clip to the same peak. `python tools/clean_wavs.py <folder>` writes `SD_card_cleaned/`, and `--loud` writes the compressed `SD_card_loud/`.

## Libraries

`FastLED`, `TMRpcm` (+ `SD`, `SPI`), `LCD_I2C`, `elapsedMillis`, `ResponsiveAnalogRead`. All of them are in the Arduino Library Manager.
