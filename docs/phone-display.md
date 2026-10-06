# Phone display: live score, score buttons and settings over Bluetooth LE

**Status (October 2026):** built, deployed and field-tested on the real scoreboard with an Android phone (Chrome) and, less reliably, an iPhone (Bluefy app). The page is live at **https://jakabo27.github.io/Gesture-Controlled-Volleyball-Scoreboard/** and works with no Wi-Fi.

## What it does

* Shows the score in huge seven-segment digits in the team colors, copied from what the LEDs are showing, with a **game clock** that starts at the first point and freezes when the game is won.
* **+ / − buttons** under each team change the scoreboard's score exactly as its own buttons do.
* **T-Pose Detection switch**: turns the Pi's gesture scoring off and on from the phone (for example if false positives show up in a game). The camera keeps seeing and recording gestures, but they stop changing the score. It is always on after a boot.
* **Settings** (sport, game-to 15/21/25, scoring sound) change the scoreboard itself and are reported back, so the buttons always show what the board really has, including changes made with its own button chords.
* Works offline from the home screen. Day theme for sun, night theme for stadium lights, mirrored layout for a phone sitting on top of the board facing the scorekeeper.

Hard rule from the start: **the Arduino keeps working 100% without the Pi or a phone.** It only broadcasts its state; nothing ever waits for an answer.

## Why Bluetooth LE + a web page

| Option | Verdict |
|---|---|
| Phone hotspot, Pi joins it | Needs a tap every game, costs battery, Android randomizes the subnet |
| Pi as a Wi-Fi access point | Reworking Wi-Fi is the riskiest change on a hard-to-reach Pi, and phones fight networks with no internet |
| **Bluetooth LE + Web Bluetooth page** | **Chosen.** No Wi-Fi at all, the phone keeps mobile data, nothing to install (Chrome on Android) |
| Native app | Possible later (same GATT service); would also fix iPhone and auto-reconnect |

## Architecture

```
                 state (one-way, checksummed)               BLE GATT notify
Arduino Mega ───────────────────────────────▶ Pi 4 ───────────────────────────▶ phone page
        ◀─────────────────────────────────────       ◀───────────────────────────  (Chrome / Bluefy)
      hello + gestures (vision engine) and           writes: score, settings,
      phone commands (link service), checksummed     T-pose switch, hello
```

### 1. Arduino → Pi (UART, Mega Serial3, 38400 baud)

The Arduino sends one line on every change (at most every 100 ms), and at least once a second:

```
$S,<home>,<away>,<sport>,<gameTo>,<piOn>,<homeColor>,<awayColor>,<d0>,<d1>,<d2>,<d3>,<event>,<eventSeq>,<soundMode>,<clockSecs>,<clockRunning>*<XOR>
```

* Colors are the slider's FastLED hue (0–255), 256 white, 257 rainbow. `d0`–`d3` are the glyphs the display actually drew (tennis `Ad`, blank leading zero), so the phone never re-implements scoring rules.
* `event` says what caused the last change (`HU HD AU AD` buttons, `HP AP` T-pose, `HC AC` cobra, `RS`, `HW AW` win, `MD`, `GT`, `SM`) so the phone can show "HOME +1 · T-pose" once.
* **The game clock lives on the scoreboard.** It starts at the first point after 0–0, freezes on a win, resumes if the winning point is undone, and resets at 0–0. An earlier version kept the clock on each phone and showed 4 h 30 min after switching phones; one source of truth fixed that.
* The line is written only if it fits in the 64-byte TX buffer, so a missing Pi changes nothing. Pi → Arduino commands (`$C,…*XOR`) are read without blocking and checksum-checked: `MODE`, `TO`, `SOUND`, `SCORE,HU|HD|AU|AD`.
* The button actions are shared functions, so a phone tap and a physical press run the same code (the phone has a 250 ms rate limit).

### 2. Wiring

The Pi 4 has spare PL011 UARTs; the Arduino link uses **UART2 on GPIO 0/1** (`dtoverlay=uart2`, appears as `/dev/ttyAMA1`), which leaves Bluetooth its own port.

| Wire | From | Via | To |
|---|---|---|---|
| State | Mega **pin 14 (TX3)** | 5.1k series, 10k to GND (5 V → 3.3 V) | Pi pin 28 (GPIO 1, RXD2) |
| Commands | Pi pin 27 (GPIO 0, TXD2) | 1k series (protection) | Mega **pin 15 (RX3)** |
| Ground | the existing common ground | | |

Serial1 (pins 18/19) was already wired to an unused level shifter, which is why Serial3 is used.

### 3. The Pi link service ([`pi/scoreboard_link.py`](../pi/scoreboard_link.py))

A separate low-priority process from the vision engine, so a crash here can never affect scoring. It reads the UART, keeps the latest valid line, and serves a BlueZ GATT service over D-Bus (no pip installs):

* **State** characteristic (read + notify), a 19-byte packet (`PACKET_FORMAT`): scores, mode, colors, glyphs, event, flags (Pi connected, data fresh, T-pose on, sound mode, clock running, detection strictness in bits 6-7) and the clock seconds. Sent on every change and as a keep-alive every 2 s so the phone can tell a dead link from a quiet game.
* **Command** characteristic (write): only whitelisted text (`COMMAND_RE`) is accepted. `SCORE`, `MODE`, `TO` and `SOUND` are forwarded to the Arduino. **`TPOSE,0|1` is handled on the Pi:** it creates or removes `/dev/shm/scoreboard_tpose_disabled`, and the vision engine skips its score pulses while that file exists (detection, logging and captures continue). `/dev/shm` is a RAM disk, so every boot starts with detection on. **`STRICT,0-3` is also handled on the Pi** (Settings > Detection: Stricter / Standard / Looser / Loosest): it is written atomically to `/home/pi/Documents/scoreboard_strictness.txt` (kept on the SD card, so it survives a reboot; missing or damaged means Standard), the vision engine re-reads it about once a second, and the Pi reports it back in bits 6-7 of the flags byte so every phone shows the current choice. The four presets are in `STRICTNESS_PRESETS` in `PoseEstimationJT_Optimized.py` (engineering log section 35).
* Advertises only the name **Scoreboard** (a 128-bit UUID plus the name would not fit in the 31-byte advertisement), so the page filters on the name.

### 4. The page ([`web/`](../web/))

A static, dependency-free page on GitHub Pages (Web Bluetooth needs https), installable to the home screen and served from a service-worker cache so it works with no signal. A content-security policy limits it to its own files. LED colors are copied from the sketch's FastLED math; the strip is wired GRB while the sketch declares RGB, so the phone swaps red and green to match what the LEDs actually show.

### 5. Staying safe in a crowd

* **Manual connect.** The Pi is not pairable and forgets any bond at startup (a stale bond made iPhones show endless pairing prompts); the page connects only when you tap Connect (auto-reconnect is an opt-in setting).
* **Hello handshake.** A phone must write `HELLO,<token>` within 8 s of connecting or the Pi disconnects it, commands from phones that haven't said hello are refused, and a phone that stops saying hello (the page repeats it every 30 s) is dropped after 75 s so a dead connection can't lock others out. The token is in the public page source, so this is a courtesy lock that keeps other Bluetooth apps out, not a secret.
* One phone connects at a time, and the Pi can't advertise while connected.

## Deploying

1. Flash the Mega with [`arduino/`](../arduino/) (Arduino IDE, board "Mega 2560").
2. Wire the two pink wires above.
3. On the Pi: `dtoverlay=uart2` in `/boot/config.txt` (instead of `disable-bt`), add `pi` to the `bluetooth` group, install `pi/scoreboard_link.py` and the units in `pi/systemd/` (`scoreboard-link.service`, `scoreboard-bt.service/.timer`, the `bluetooth.service.d` drop-ins). Bluetooth starts 20 s after boot so it never delays the vision engine. Details: [`pi-setup-from-scratch.md`](pi-setup-from-scratch.md).
4. Enable GitHub Pages (Settings → Pages → Source: GitHub Actions) and push `web/` to `main`; the workflow runs the tests and publishes.

## iPhone

Safari and Chrome on iOS have no Web Bluetooth. The free **Bluefy** app adds it, and the page works there (connect, score, buttons, settings), but BlueZ 5.50 on the Pi's Raspbian Buster crashed when an iPhone connected, and Bluefy sometimes stops delivering notifications (the page then polls four times a second). Mitigations: `bluetoothd` restarts itself within 2 s, the Pi is built against **BlueZ 5.79** (see below), and the page hides the fullscreen button on iOS (use Bluefy's own). Android with Chrome is the reliable path.

### Newer BlueZ

[`pi/bluez-build.sh`](../pi/bluez-build.sh) builds BlueZ 5.79 into `/usr/local` (about 8 minutes on a Pi 4, run detached). It installs only `-dev` packages and never touches Wi-Fi, the kernel or firmware; a systemd drop-in (`pi/systemd/bluetooth.service.d/20-newbluez.conf`) points the Bluetooth service at the new binary, and deleting that file rolls back. Do not disable the audio profiles when configuring, or the remaining audio code fails to link.

## Tests

* `python tests/test_link_protocol.py` pulls the `snprintf` format straight out of the sketch, builds lines exactly like the Arduino, and checks parsing, checksum rejection, the packet size, the command whitelist (including that the page, the Pi and the sketch agree) and the T-pose switch. It writes `tests/fixtures/state_packets.json`.
* `node tests/test_protocol.js` decodes those packets with the page's `protocol.js`, checks the FastLED color port and swap, the digit table against the sketch, and that the page and Pi agree on the hello token and command list.
* Both run in CI before every Pages deploy.

## Lessons

* **A 19-byte packet fits the default Bluetooth write size**; keeping it under 20 bytes avoided long reads and negotiation.
* **Never refresh the LEDs while a sound clip plays.** A 252-LED frame takes ~8 ms with interrupts off, which the WAV player needs; refreshing the heartbeat dot at the instant "Raspberry Pi connected" started made the first word stutter.
* **Old BlueZ is the weak link.** Version 5.50 can't advertise while connected, segfaults with some iPhones, and keeps stale bonds; a newer build, `Pairable=no`, and automatic restarts fixed most of it.
* **Debug output can break the thing you are debugging.** The USB serial buffer is 64 bytes, so a "print only when there is room" check needs a threshold below that.
