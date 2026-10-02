# Plan: live score on my phone over Bluetooth LE

**Status (October 2026):** software written and tested on the bench (branch `phone-display`): Arduino firmware compiles, the protocol tests pass, the link service runs on the Pi's Python 3.7, and the page works in demo mode. **Not deployed yet:** it needs the two wires and the `config.txt` change below, so it waits for physical access. See the [deploy checklist](#deploy-checklist-needs-physical-access).

## Goal

Show the live score in huge digits on my phone (a Galaxy S24, Android) courtside, and later control it (+1 / −1) from the phone. Constraints:

* **The Arduino must keep working 100% without the Pi.** Manual scoring is the priority.
* **No special Wi-Fi.** There's usually no Wi-Fi at the courts, and the phone shouldn't have to join a scoreboard network.
* Only one phone needs to work, so a custom page or app is fine.

## Why Bluetooth LE + a Chrome page

| Option | Verdict |
|---|---|
| Phone hotspot, Pi joins it, web page | Runner-up. Lowest Pi risk, but needs a tap on the hotspot every game, costs battery, and Android randomizes the hotspot subnet |
| Pi as a Wi-Fi access point | Reworking the Pi's Wi-Fi is the riskiest change on a hard-to-reach Pi, and Samsung's "switch to mobile data" fights networks with no internet |
| **Bluetooth LE + Web Bluetooth page in Chrome** | **Chosen.** No Wi-Fi at all, the phone keeps mobile data, and Chrome on Android supports Web Bluetooth |
| Bluetooth LE + native Android app | Later. Fully automatic reconnect and a notification with the score. It uses the same GATT service, so no Pi changes are needed |

## Architecture

```
Arduino Mega ──UART (one-way state broadcast)──▶ Pi 4 ──BLE GATT notify──▶ Chrome on the phone
     ▲                                           │
     └──────────── existing GPIO pulses ─────────┘   (phone control later: UART commands)
```

### 1. Arduino → Pi state link (UART)

* Mega **Serial1** at **38400 baud** (0.2% baud error on a 16MHz AVR, against 2.1% at 115200).
* The Arduino sends one checksummed line on every change (rate-limited to 100ms, because the color sliders call `UpdateDisplay()` repeatedly) and once a second regardless:
  `$S,<home>,<away>,<sportMode>,<scoreTo>,<piOn>,<homeColor>,<awayColor>,<d0>,<d1>,<d2>,<d3>,<event>,<eventSeq>*<xor>`
* Colors are the slider's FastLED hue (0–255), 256 for white or 257 for rainbow. `d0`–`d3` are the glyphs `UpdateDisplay()` actually drew (tennis `Ad`, blank leading zero = −1), so the phone never re-implements scoring rules.
* `event` records what caused the last change (`HU`/`HD`/`AU`/`AD` buttons, `HP`/`AP` T-pose, `HC`/`AC` cobra, `RS`, `HW`/`AW` win, `MD`, `GT`, `SM`), and `eventSeq` counts them, so the phone can flash "HOME +1 · T-pose" once.
* The state is also sent right before the blocking win song and the button-release waits, so the phone sees the winning point immediately.
* **Never blocks:** the sketch checks `Serial1.availableForWrite()` first and skips a line rather than waiting, so a missing Pi changes nothing.

### 2. Wiring

The Pi 4 has extra PL011 UARTs. The Arduino goes on **UART2 (GPIO 0/1)**, so Bluetooth can have the main PL011 back. The alternative (`miniuart-bt`) would also mean editing `cmdline.txt` and locking the core clock.

| Wire | From | Via | To |
|---|---|---|---|
| State (Arduino → Pi) | Mega pin 18 (TX1) | 10k series, 20k to GND (5V → 3.3V) | Pi pin 28 (GPIO 1, RXD2) |
| Commands (Pi → Arduino, later) | Pi pin 27 (GPIO 0, TXD2) | 1k series (protection only) | Mega pin 19 (RX1) |
| Ground | existing common ground | | |

The Pi's firmware probes GPIO 0/1 for a HAT EEPROM at boot. The Mega will see a few junk bytes then, and the checksums reject them.

### 3. Pi configuration (needs physical access)

* `/boot/config.txt`: remove `dtoverlay=disable-bt`, add `dtoverlay=uart2`. That's the only boot-file change: no `cmdline.txt` edit, no clock locking.
* The Arduino link appears as `/dev/ttyAMA1`.
* Add `pi` to the `bluetooth` group (BlueZ's D-Bus policy).
* Keep `hciuart` and `bluetooth` disabled at boot, and start them from a systemd timer about 20s after boot, so Bluetooth never competes with getting the vision engine running.
* Rollback: put the SD card in a PC and restore the original `config.txt` (the `/boot` partition is FAT).

### 4. Pi `scoreboard-link` service ([`pi/scoreboard_link.py`](../pi/scoreboard_link.py))

* A separate process from the vision engine (`scoreboard-link.service`, lower priority), so a crash here can't affect scoring.
* Reads the UART from boot and keeps the latest valid line (checksummed; boot noise and partial lines are dropped) even before Bluetooth is up.
* BlueZ 5.50 GATT server and LE advertisement over D-Bus (`python3-dbus` + `python3-gi`, both already installed, so no `pip` installs on the Pi). It retries every 5s until `bluetoothd` appears and re-registers if it restarts.
* Service `b3710001-…`, characteristic **State** `b3710002-…` (read + notify): 17 bytes, see `PACKET_FORMAT`. It's sent on every change, plus a keep-alive every 2s so the phone can tell a dead link from a quiet game. **Command** (write, pairing required) comes with phone control.
* Advertises only the name **Scoreboard**: name + 128-bit UUID wouldn't fit in 31 bytes, so the page filters on the name.
* Re-registers the advertisement after every disconnect (BlueZ 5.50 can stop advertising after a central disconnects).
* `python3 scoreboard_link.py --stdin --no-ble` parses lines from stdin and prints packets, for testing without hardware.

### 5. Phone page ([`web/`](../web/))

* Static page on GitHub Pages (Web Bluetooth needs https), installable to the home screen and cached for offline use.
* **Bold solid seven-segment digits** in the team colors. The **Day** theme (white, darkened team colors at ≥4.5:1 contrast) is for noon sun, and the **Night** theme (black, brightened colors, soft glow) is for stadium lights. An optional colored-background style fills each half with its team color.
* Mirrored by default (AWAY left, HOME right) for a phone sitting on top of the scoreboard facing the scorekeeper. One setting flips it.
* Connect → choose "Scoreboard" → notifications, with automatic reconnects. Also a point banner, a Pi gestures indicator, a stale-data warning, screen wake lock and full screen.

## Tests

* `python tests/test_link_protocol.py`: pulls the `snprintf` format straight out of the sketch, builds lines exactly like the Arduino, and checks parsing, checksum rejection, the packet size and staleness. It also writes `tests/fixtures/state_packets.json`.
* `node tests/test_protocol.js`: decodes those packets with the page's `protocol.js`, checks the FastLED color port against known values, and checks the page's digit table against the sketch's `digitTable`.
* Both run in CI before every Pages deploy.

## Deploy checklist (needs physical access)

Do it in this order; each step can be checked before the next. The scoreboard keeps working at every step.

1. **Flash the Arduino** with the `phone-display` branch sketch. Nothing changes on the scoreboard. With USB connected, the serial monitor still shows the old debug output.
2. **Wire it** (both wires, see the table above). Use a 10k + 20k divider on the Mega TX1 → Pi pin 28 line (two 10k in series work for the 20k). Measure the divider output with a multimeter before connecting it to the Pi: it should idle at ~3.3V, never 5V.
3. **Pi boot config.** Back up `/boot/config.txt`, replace `dtoverlay=disable-bt` with `dtoverlay=uart2`, then reboot. Check that SSH and Wi-Fi still work, `ls -l /dev/ttyAMA1` exists, and `journalctl -u scoreboard` shows the usual ~2.9 fps.
4. **Check the UART:** `sudo systemctl stop scoreboard-link 2>/dev/null; python3 -c "import serial; s=serial.Serial('/dev/ttyAMA1',38400,timeout=2); print(s.readline())"` should print a `$S,...` line within a second.
5. **Install the link service and the delayed Bluetooth start** (run from a copy of the repo's `pi/` folder on the Pi):
   ```bash
   sudo usermod -aG bluetooth pi
   sudo systemctl disable hciuart bluetooth        # started by the timer instead
   sudo cp systemd/scoreboard-link.service systemd/scoreboard-bt.service systemd/scoreboard-bt.timer /etc/systemd/system/
   cp scoreboard_link.py /home/pi/Documents/
   sudo systemctl daemon-reload
   sudo systemctl enable --now scoreboard-bt.timer scoreboard-link.service
   journalctl -u scoreboard-link -f
   ```
   Expect `UART open`, then (~20s after boot) `adapter /org/bluez/hci0`, `GATT service registered` and `advertising as "Scoreboard"`.
6. **nRF Connect** on the phone: scan for "Scoreboard", connect, subscribe to `b3710002-…` and press a score button. The value should change.
7. **The page:** merge to `main` (the Pages workflow publishes `web/`), open it in Chrome, Connect.
8. **Reboot test:** power-cycle the whole scoreboard. Scoring should start as before (Bluetooth doesn't start until 20s), and the phone should reconnect by itself.

**Rollback:** `config.txt` back to `dtoverlay=disable-bt` (on the Pi, or from a PC: `/boot` is FAT), and `sudo systemctl disable --now scoreboard-link scoreboard-bt.timer`. The Arduino firmware doesn't need to be rolled back: with nothing on TX1 it behaves exactly as before.

## Risks to test early

* BLE range through the enclosure (the Pi's antenna is on the board).
* Wi-Fi + Bluetooth coexistence on the Pi's shared radio (SSH at home).
* BlueZ 5.50 advertising behaviour across reconnects. If Chrome's chooser doesn't list "Scoreboard", the advertisement may lack the discoverable flag: setting the adapter `Discoverable` is the fallback to try.
