# Plan: live score on my phone over Bluetooth LE

**Status:** planned (October 2026). Nothing in this document is deployed yet.

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
  `$S,<seq>,<home>,<away>,<mode>,<scoreTo>,<piOn>,<homeHue>,<awayHue>,<event>*<xor>`
* `event` records what caused the last change (button, T-pose, cobra, reset, win), so the phone can flash "T-pose, home!".
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

### 4. Pi `scoreboard-link` service

* A separate process from the vision engine, so a crash here can't affect scoring.
* Reads the UART from boot and keeps the latest state even before Bluetooth is up.
* BlueZ 5.50 GATT server and LE advertisement over D-Bus (`python3-dbus` + `python3-gi`, both already installed, so no `pip` installs on the Pi).
* One custom service: **State** (read + notify, packed into 20 bytes or less to fit the default MTU), and later **Command** (write, pairing required).
* Re-registers the advertisement after every disconnect (BlueZ 5.50 can stop advertising after a central disconnects).
* Checked first with the nRF Connect app before the page exists.

### 5. Phone page

* Static page on GitHub Pages (Web Bluetooth needs https), installable to the home screen and cached for offline use.
* Connect → choose "Scoreboard" → notifications. It reconnects by itself after drop-outs within a session. Chrome's `getDevices()` permissions flag may allow reconnecting without the chooser after a reload.
* Huge digits in the LED colors, game-to, a Pi-connected dot, a flash on points, a stale-data warning, screen wake lock and full screen.

## Risks to test early

* BLE range through the enclosure (the Pi's antenna is on the board).
* Wi-Fi + Bluetooth coexistence on the Pi's shared radio (SSH at home).
* BlueZ 5.50 advertising behaviour across reconnects.
