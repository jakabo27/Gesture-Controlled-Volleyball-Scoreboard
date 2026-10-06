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
| 14 / 15 (TX3 / RX3) | Serial link to the Pi, 38400 baud. TX3 sends the score state (through a 5.1k/10k divider to the Pi's 3.3V RX); RX3 receives the Pi's hello, gestures and the phone's commands |
| 45 / 47 | Legacy from Pi: home +1 (camera right) / away +1 (camera left). Only read for an older engine (hello version 1) |
| 42 / 43 | Legacy from Pi: home −1 / away −1 (cobra). Same; no signal reaches 42 |
| 46 / 44 | Legacy heartbeat (ignored) / spare |

## Controls

| Action | Result |
|---|---|
| + / − | Change that team's score (held: repeats every 500ms) |
| Reset | 0–0 and re-arm the win celebration |
| Any 2 score buttons together | Volleyball: cycle game-to **21 → 25 → 15** (announced) |
| Any 3 score buttons together | Cycle the **sound mode**: sound effects (default) → voice ("Point home" / "Point away" on + presses) → plain tones |
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

* **The serial hello is the only sign of life.** The vision engine sends `$C,PI,<version>*XX` about once a second while camera frames are flowing. The link is up from the first hello and down 4s after the last one. Both are announced (`PiCon.wav` / `PiDis.wav`), so you know whether gestures are live, and each hello blinks the heartbeat pixel (LED 126).
* **Gestures are messages, not wire levels.** A version-2 engine sends `$C,PT,<LP|RP|LC|RC>,<id>*XX`: the camera's **L**eft or **R**ight half, a T-pose **P**oint (+1) or **C**obra (−1). The camera's left half is the away team and the right half home (`CAMERA_LEFT_IS_AWAY`). Each event comes 3 times with the same id; the last 8 ids are remembered so a copy is never counted twice, even when two events overlap.
* **Per-team cooldown.** At most one Pi gesture per team every 3s, so a point for one team never blocks the other.
* **With no Pi nothing changes.** If the Pi is off, booting, shutting down or hung, no hello arrives and the Mega ignores every Pi input, including whatever the GPIO wires do while the Pi boots (it pulls GPIO 0–8 high for ~17s). The buttons, sliders, display and sounds never depend on the Pi.
* **Older engines (hello version 1)** still pulse the GPIO wires. Those pulses count only while that engine's hello is fresh, and only if they are 15–400ms wide, so a line that just sits high is never a point.
* The heartbeat-period logic this replaced compared toggle times with **signed** `long`s: an `unsigned long` version made `prev - range` wrap to ~4.29 billion for any period under 700ms, so the Pi always "disconnected" about 7s after connecting.

## State broadcast for the phone display

Once per change (at most every 100ms) and at least once a second, `sendStateIfDue()` writes one checksummed line on Serial3:

```
$S,<home>,<away>,<sportMode>,<scoreTo>,<piOn>,<homeColor>,<awayColor>,<d0>,<d1>,<d2>,<d3>,<event>,<eventSeq>*<XOR>
```

The fields are: the scores, the mode and game-to, whether the Pi is trusted, both team colors (FastLED hue, 256 white, 257 rainbow), the four glyphs `UpdateDisplay()` drew, and what caused the last change. The line is only written if the whole thing fits in the TX buffer, so with nothing connected (or a dead Pi) the scoreboard behaves exactly as before. The format is checked by [`tests/test_link_protocol.py`](../tests/test_link_protocol.py).

## Commands from the Pi (phone settings)

`serviceSerialCommands()` reads Serial3 RX (pin 15, from the Pi's pin 27 through 1k) without blocking. It accepts only these checksummed lines:

```
$C,MODE,<0|1>*<XOR>        sport: 0 volleyball, 1 tennis (resets the score, like the 4-button chord)
$C,TO,<15|21|25>*<XOR>     volleyball game-to
$C,SOUND,<0|1|2>*<XOR>       sound mode: 0 effects, 1 "Point home/away" voice, 2 tones (same as the 3-button chord)
$C,SCORE,<HU|HD|AU|AD>,<id>*<XOR>  phone +/- buttons: the same code as the physical buttons (taps closer than 250ms are ignored); each tap is repeated 3 times with one id and applied once
$C,PI,<1|2>*<XOR>             hello from the vision engine, about once a second (see "How it trusts the Pi")
$C,PT,<LP|RP|LC|RC>,<id>*<XOR>  gesture from the vision engine: camera half + T-pose point or cobra, 3 copies per id
```

Anything else (boot noise, a half line, a wrong checksum) is ignored. The new setting shows up in the next state line, which is how the phone confirms it.

## Loudness

The firmware already drives the speaker as hard as it can without clipping, so the volume is limited by the clips and the amplifier.

* **How TMRpcm drives pin 5:** with `quality(1)` and 16kHz files, the PWM runs at 32kHz with **500 steps** of range. `setVolume(5)` doubles every 8-bit sample (0–255 → 0–510), so a full-scale clip spans the whole range. `setVolume(6)` would quadruple it and clip hard, so 5 is the maximum.
* **The original clips only reached 26–47% of full scale,** so the speaker got a quarter to half of the possible swing. `tools/clean_wavs.py` normalizes every clip to a peak of 120/127 (about 97% of the PWM range): **+3 to +7 dB** on the voice clips. `python tools/clean_wavs.py --loud <folder>` also applies look-ahead compression (same peak, quieter parts of each word lifted) for about **+2 to +4 dB more** on speech. Copy `SD_card_loud/*.wav` to the SD card.
* **The beeps (voice mode off, or no SD card) were nearly silent for two reasons, both fixed:**
  1. After any WAV (the boot sound always plays), TMRpcm leaves Timer3's PWM output connected to pin 5. `tone()` toggles the pin's port bit, which the timer then overrides, so the beeps were faint or missing. `beep()` now disconnects the timer from the pin first (`play()` reconnects it).
  2. Most beeps are 50–100 Hz, which a small speaker reproduces weakly. The original low tones are kept on purpose (`BEEP_PITCH 1`). `BEEP_PITCH` multiplies every beep's pitch if they ever need to be louder (6 = 300 Hz–3 kHz, same pattern). The victory melodies always keep their real notes.
* **The amplifier is the ceiling now.** It's a PAM8403 module (5V, 2 × 3W, volume pot; bought Dec 27, 2021). Its inputs are single-ended (L / R / G, with G = power ground), so `BRIDGED_AUDIO` must stay 0 with it. The Arduino's 5V PWM is a hot input for its fixed 24 dB gain, so past roughly the first third of the knob it mostly adds distortion, not volume. A TPA3110 or TPA3116D2 board powered straight from the Ryobi battery (through its own fuse) can deliver about 15–35W instead of ~3W: **+7 to +10 dB**. It also takes the amp off the 5V rail, which sags when the LEDs are bright.
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
