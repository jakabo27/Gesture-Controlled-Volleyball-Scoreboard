# Plan: Pi → Arduino points over the serial link (retire the GPIO pulse wires)

**Status:** flashed and deployed on Oct 5 2026 and bench-tested against the real Mega (results below). Branch `serial-points`, merged to `main`.

**Decisions (Oct 5):**
1. No "Swap sides" button: teams don't switch sides mid-game. The camera's **left half is the away team, the right half home**, which matches how the wires are actually connected today (`CAMERA_LEFT_IS_AWAY` in the sketch).
2. The heartbeat pixel stays as it is (LED 126), now blinking on each serial hello.
3. The Mega's 3 s cooldown is **per team**.
4. The GPIO wires stay connected (unused, held low by the Pi).
5. The physical buttons remain the primary interface: none of their code changed, and with the Pi off the Mega ignores every Pi input.

## Goal

Send every Pi → Arduino signal over the existing serial link (Pi UART2 → Mega Serial3) instead of the six GPIO wires:

| Today (GPIO) | After (serial) |
|---|---|
| Home +1, Away +1: 50 ms pulses on 2 wires | One checksummed message per point, sent 3 times with an id |
| Home −1, Away −1 (cobra): 2 more wires | Same message type |
| Heartbeat: a wire toggling every 1 s, timed by the Mega | The hello message the engine already sends every second |
| Heartbeat LED (pixel 126): follows the heartbeat wire | Toggles on each hello |
| Spare wire | Unused |

The Arduino still never depends on the Pi: with no Pi, or a Pi that is booting, crashed or switched off, nothing arrives and the scoreboard runs on its buttons exactly as it does today.

## Why

Things this session ran into that all trace back to the GPIO wires:

1. **Phantom points at Pi boot and shutdown.** The Pi pulls GPIO 0–8 high for ~17 s while it boots, which the Mega counted as "Point home" every 3 s. This is fixed now with a pulse-width check plus the hello handshake, but only by layering two workarounds on top of the wires.
2. **Home/away crossed, and one dead wire.** The bench test showed the engine's "home" wire (GPIO 6) arrives on the Mega's *away* input (47), GPIO 5 on *home* (45), GPIO 19 on *cobra away* (43), and GPIO 21 never reaches the Mega at all (4 of 4 pulses lost). With serial, sides are named in the message, so the wiring can't get them wrong.
3. **Timing-sensitive detection.** A 50 ms pulse is only seen if `loop()` comes round in under 50 ms. Measured `maxLoopMs` is 11 ms normally, but 55–81 ms right after a clip starts (SD file open). A serial message waits in the 64-byte RX buffer instead.
4. **Fragile heartbeat logic.** About 80 lines compare consecutive toggle periods, with an "instant connect" special case, a 7 s grace, an irregular-streak counter, and `Serial.println("sup")` debug spam on every edge.
5. **The heartbeat LED forces a strip refresh every second.** That's ~8 ms with interrupts off, which tore incoming serial bytes and made "Raspberry Pi connected" stutter.

## Design

### Messages, Pi → Mega

These use the same framing as the phone commands: `$C,<NAME>,<args>*<XOR>\r\n`, where XOR is of the characters between `$` and `*`.

| Message | Meaning |
|---|---|
| `$C,PI,2*XX` | **Hello, version 2**: "the vision engine is running and sends points over serial". Every 1 s while camera frames are flowing (same rule as today's heartbeat: it stops after 20 s without frames). Version 1 (`$C,PI,1`) is today's engine, which still uses the wires. |
| `$C,PT,<what>,<id>*XX` | **Gesture event.** `<what>` = `LP` / `RP` (T-pose on the camera's left / right half) or `LC` / `RC` (cobra on left / right). `<id>` = 1–255, increments per event (wraps 255 → 1). Each event is **sent 3 times, 150 ms apart**, with the same id. |

For example, `$C,PT,LP,17*XX` is 17 bytes with the CR/LF, or 4.4 ms at 38400 baud.

**Why camera sides (L/R) and not home/away.** The Pi reports what it saw (which half), and the Mega, which owns the score, decides which team that is with one constant (`CAMERA_LEFT_IS_AWAY 1`). A "Swap sides" setting was considered for leagues that switch sides mid-game, but isn't needed (decision 1).

### Reliability

| Risk | Handling |
|---|---|
| Bytes lost while the Mega's interrupts are off (a FastLED frame is 252 × 30 µs ≈ 7.6 ms) | 3 copies 150 ms apart. Only one copy has to survive. At an observed ~1% chance per line, losing all three is about one in a million. |
| The same event received 2–3 times | The Mega remembers the last 8 ids it applied and applies each id once (copies of two events can interleave). |
| RX buffer overflow while `loop()` stalls (up to ~80 ms at a clip start) | The Pi sends through **one sender thread that leaves ≥ 40 ms between lines**, so at most ~2 lines (34 bytes) can pile up in a stall. That's well under 64 bytes. |
| Corrupted or partial lines | The checksum already rejects them, and the Mega already logs `cmdBad`. |
| The engine restarts and its id counter starts over | The engine starts its id at a random value, and the Mega forgets its remembered ids whenever the link drops (no hello for 4 s). |
| Two Pi processes writing the same UART (the engine sends points and hello; the link service sends phone commands) | Linux serializes each `write()` call on a tty, so whole lines never interleave. The checksum covers the rest. |
| The Pi booting, shutting down, hung, or wires floating | In v2 the Mega **ignores the GPIO inputs completely**. Points only arrive as checksummed messages from a running engine. |

Latency improves slightly: the Mega acts as soon as the first copy arrives (~5 ms), instead of at the end of a 50 ms pulse.

### Mega firmware (as built)

1. **The hello replaces the heartbeat wire.** `piLinkUp` is set by the first valid hello (a checksummed line, so noise can't fake it) and cleared 4 s after the last one; `PiCon.wav` / `PiDis.wav` play on those transitions. `piVersion` holds the hello's version. The ~80 lines of heartbeat-period timing are gone.
2. **`PT` handler.** It applies a gesture only if `piLinkUp && piVersion >= 2` and the id isn't one of the last 8 applied. The 8-entry history matters because copies of two quick events can interleave (left T-pose at t, right cobra at t + 0.1 s). L/R maps to a team via `CAMERA_LEFT_IS_AWAY`, then `piGesture(home, cobra)` runs. That is the four old inline blocks, now one function with the same sounds and order.
3. **Per-team cooldown:** 3 s per team (`timePiHome` / `timePiAway`).
4. **Heartbeat pixel:** each hello toggles LED 126, as before. The strip refresh waits for a quiet moment (no line arriving, no clip playing), so it can neither tear an incoming line nor make a clip stutter.
5. **Version-gated compatibility.** With a version-1 hello (today's engine), the GPIO pulses still count: pulse-width check, per-team cooldown. With version 2 they're ignored. With no hello, nothing from the Pi counts. So the new firmware can be flashed first and works with today's engine.
6. **Phone score taps carry ids** (`$C,SCORE,HU,<id>`), repeated 3 times by the link service and applied once. A `SCORE` without an id (an older link service) still works.
7. **Debug stats** on USB serial now include `pt=`, `ptDup=` and `link=` (the hello version) for the bench tests.
8. **Later cleanup:** after a few games on version 2, delete the version-1 GPIO path (`piPulseEnded` and its pulse tracking).

### Pi side (as built)

* **`pi/arduino_protocol.py`** (new, no dependencies): the message builders and `ArduinoLink`. That's one writer thread: a hello every second while `alive()`, `send_event('L'|'R', 'P'|'C')` queues 3 copies 150 ms apart, and lines are ≥ 40 ms apart. The phone's T-pose switch is checked in `send_event`. The engine imports it, so **deploy it next to the engine**.
* **Engine:** `pulse_pin()`, `HeartbeatThread` and `ArduinoHello` are gone. `LEFT` / `RIGHT` call `arduino.send_event('L' | 'R', ...)`, and the GPIO pins stay claimed and held LOW. Sending no longer blocks the main loop; `pulse_pin()` used to take 50 ms.
* **Link service:** phone commands go through a paced writer, 3 copies each. `SCORE` gets an id, and a newer setting replaces older copies of the same setting that haven't been sent yet. State-line parsing is unchanged.

## Rollout

| Step | What | Rollback |
|---|---|---|
| 1 | Flash the new firmware. Today's engine (hello v1 + wires) keeps working. Check buttons, sliders, sounds, "Pi connected", T-poses. | Reflash `d34c6ba` |
| 2 | Deploy `arduino_protocol.py` + the engine + the link service to the Pi. The engine now says hello v2 and gestures go over serial. | Restore the engine from `~/Documents/backups/<timestamp>/`: hello v1 → the Mega uses the wires again |
| 3 | After a few games: remove the version-1 GPIO path from the firmware. | Git revert |

## Test plan

**Automated (CI), done:** `tests/test_link_protocol.py` checks:
* the hello and gesture lines, and their checksums, against what the sketch parses
* that the phone can't send `PI` or `PT`
* `CAMERA_LEFT_IS_AWAY`, and the version gates in the sketch
* `ArduinoLink` timing with a fake clock and port: a hello every second that stops after the grace, 3 identical copies per gesture, ≥ 40 ms between lines, nothing sent while the T-pose switch is off
* the link service's command copies: ids on `SCORE`, a newer setting replacing an older one, ≥ 40 ms pacing

**Bench, next time the hardware is plugged in** (UART emulator on the Pi + the Mega's USB debug output):

| # | Case | Expect |
|---|---|---|
| 1 | Buttons, chords, sliders, sounds with the **Pi off** | Exactly as before; no "Pi connected", no phantom points |
| 2 | v2 hello, then `LP` ×3 copies | Away +1 once, one sound (`pt=1 ptDup=2`) |
| 3 | `RP` then `LC` 0.1 s apart (interleaved copies) | Home +1 and away −1, each once |
| 4 | Same id again 2 s later | Ignored |
| 5 | Only the 3rd copy arrives (first two corrupted on purpose) | Counted |
| 6 | Gesture with no hello / after 4 s of silence | Ignored; "Pi disconnected" once |
| 7 | GPIO lines held high or pulsed while v2 is active | Ignored |
| 8 | v1 hello + GPIO pulses (today's engine) | Still works |
| 9 | 500 random gestures over 30 min while moving sliders and playing clips | Every id applied exactly once |
| 10 | Pi reboot / Pi off / Mega reset while the Pi runs | No phantom points; one connect announcement |
| 11 | Phone + / − taps, fast double taps, sport / game-to / sound | Each tap once; settings end where the last tap left them |
| 12 | Real T-poses on both halves | Camera-left scores away, camera-right scores home |

**Bench results (Oct 5 2026, Mega on COM18, harness driving /dev/ttyAMA1 with the engine's own `ArduinoLink`; the Mega's USB counters read `pt=124 ptDup=247`, i.e. every gesture applied once):**

| # | Result |
|---|---|
| 1 | Pi-off boot checked (scores 0/0, no Pi link, no phantom points). Button, chord and sound behaviour **not retested** here: that code is unchanged and physical presses were seen working during the run. |
| 2 | Pass: camera-left T-pose = away +1 once, 2 duplicate copies counted in `ptDup` |
| 3 | Pass: interleaved right T-pose + left cobra = home +1, away -1 |
| 4 | Pass: an id replayed 2 s later is ignored |
| 5 | Pass: two corrupted copies + one good copy = counted once |
| 6 | Pass: the link drops about 4 s after the last hello and a gesture sent then is ignored; a new hello brings it back |
| 7 | Pass: GPIO pulses and held-high wires ignored while v2 hellos arrive |
| 8 | Pass: with a v1 hello the wires score again (GPIO 6 = away +1, GPIO 5 = home +1, GPIO 19 = away -1) |
| 9 | Pass: 120 random gestures in about 5 minutes, each applied exactly once, checked against an exact score model (not yet the full 500 over 30 min). The first run showed 8 mismatches while about 20 physical buttons were pressed in the middle of it; a repeat with nobody touching the buttons was clean |
| 10 | **Not run:** Pi reboot / Mega reset while the Pi is running |
| 11 | Pass: phone-style `SCORE` taps (3 copies, with and without id), quick taps on both teams, game-to and sound settings. Sent as serial lines; the BLE side was not re-tested |
| 12 | **Pending:** real T-poses on both halves |

About 1% of lines arrive damaged while the Mega refreshes its LEDs or starts a clip (8 of about 800 here: 2 deliberate, 6 truncated hellos), as the plan expected; the 3 copies and the 1 s hello absorb it.

**At the court:** one game with a phone connected. Afterwards, compare the engine's `[ARDUINO] gesture` log lines with the Mega's applied events.
