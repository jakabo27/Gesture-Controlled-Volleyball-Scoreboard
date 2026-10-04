# Setting up the vision Pi from scratch (V2 / rebuild guide)

Everything needed to take a blank SD card (or a new Pi / compute module) to a working scoreboard brain, including **how the Python starts on boot**. Values are from the running scoreboard as of October 2026.

## How it starts on boot (the whole chain)

```
power on
 └─ Pi firmware reads /boot/config.txt        (overlays: SPI, I2C, UART2, Bluetooth on/off, boot speed-ups)
     └─ Linux kernel  (/boot/cmdline.txt)
         └─ systemd
             ├─ local-fs.target  ──▶  scoreboard.service        python3 PoseEstimationJT_Optimized.py   (~6 s after power)
             │                         + scoreboard.service.d/10-safety.conf   (Nice=10, threads, no .pyc)
             ├─ local-fs.target  ──▶  scoreboard-link.service   python3 scoreboard_link.py              (phone display)
             └─ timers.target    ──▶  scoreboard-bt.timer  ──(20 s after boot)──▶  scoreboard-bt.service
                                                                 └─ systemctl start hciuart bluetooth
```

* Nothing waits for the network, the desktop or a login: the units start from `local-fs.target`, so the scoreboard works at a court with no Wi-Fi.
* `Restart=always` on both Python services. `scoreboard.service` also has an in-process watchdog that exits if the main loop stalls for 60s, and systemd restarts it.
* The old way (a desktop autostart entry, `/etc/xdg/autostart/myapp.desktop`) is retired: it was renamed to `.bak` so only one copy runs. Don't bring it back.
* Unit files are in [`pi/systemd/`](../pi/systemd/). Logs: `journalctl -u scoreboard -f` and `journalctl -u scoreboard-link -f`.

## 1. Hardware

* Raspberry Pi 4 Model B (2GB is plenty). **UART2 on GPIO 0/1 is a Pi 4 (BCM2711) feature.** See "Moving to different hardware" below.
* Wide-angle USB camera with hardware MJPG (Arducam 1080p low-light WDR, USB ID `0c45:6366`)
* Adafruit 1.5" SSD1351 OLED on SPI0, power button on GPIO 12, and the harness to the Arduino Mega: see [`media/diagrams/wiring-pi-to-arduino.svg`](../media/diagrams/wiring-pi-to-arduino.svg). The **pink** wires are the phone-display UART.
* A good SD card (high-endurance if you keep the field captures on).

## 2. OS

The current Pi runs **Raspbian Buster 32-bit** (armv7l, Python 3.7.3, kernel 5.10). The software stack below was built for that. A V2 on a newer OS (Bookworm, 64-bit) should work and run faster, but pip packages will need newer versions (see the notes at the end).

1. Flash Raspberry Pi OS Lite with Raspberry Pi Imager. In its settings: hostname `scoreboard-pi`, user `pi`, your Wi-Fi networks, and SSH enabled.
2. `sudo raspi-config`: enable **SPI** and **I2C**, set the locale/timezone, and expand the filesystem (newer images do this automatically).
3. Keep `raspi-config.service` enabled. On Buster it switches the CPU governor from `powersave` to `ondemand`. Disabling it left the CPU at 600MHz and the vision loop took 2.4s instead of 0.34s. Check with `cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor` (`ondemand`).

## 3. `/boot/config.txt`

Add or confirm these (the full snapshot is [`pi/boot-config.txt`](../pi/boot-config.txt)):

```ini
dtparam=spi=on            # SSD1351 OLED
dtparam=i2c_arm=on
enable_uart=1
dtoverlay=uart2           # phone display: Arduino link on GPIO 0/1 -> /dev/ttyAMA1 (Pi 4 only)
# do NOT add dtoverlay=disable-bt any more: Bluetooth is needed for the phone display
boot_delay=0              # faster boot
disable_splash=1
initial_turbo=30          # full clock for the first 30 s of boot
```

Reboot after editing. **Before** the phone display, the scoreboard had `dtoverlay=disable-bt` instead of `dtoverlay=uart2`. That line is the only boot-file difference between the two setups.

`/boot/cmdline.txt` stays stock apart from `fsck.repair=yes` (repair the filesystem automatically after a power cut, never stop at a prompt).

## 4. Packages

```bash
sudo apt update
sudo apt install -y python3-pip python3-numpy python3-serial python3-dbus python3-gi \
                    libatlas-base-dev libopenjp2-7 bluez pi-bluetooth
pip3 install opencv-python==4.5.5.62 Pillow adafruit-blinka \
             adafruit-circuitpython-rgb-display adafruit-circuitpython-ssd1351 psutil
```

**tflite-runtime 2.7.0 with multithreading** is [PINTO0309's armv7l build](https://github.com/PINTO0309/TensorflowLite-bin) for Python 3.7:

```bash
wget "https://raw.githubusercontent.com/PINTO0309/TensorflowLite-bin/main/2.7.0/download_tflite_runtime-2.7.0-cp37-none-linux_armv7l.whl.sh"
bash download_tflite_runtime-2.7.0-cp37-none-linux_armv7l.whl.sh
sudo pip3 install --upgrade tflite_runtime-2.7.0-cp37-none-linux_armv7l.whl
```

Known-good versions on the current Pi: tflite-runtime 2.7.0, opencv-python 4.5.5.62, numpy 1.19.5, Adafruit-Blinka 6.20.1, adafruit-circuitpython-rgb-display 3.10.10, adafruit-circuitpython-ssd1351 1.3.1, Pillow 9.0.0, pyserial 3.4, BlueZ 5.50.

## 5. Files

Copy the repo's `pi/` folder contents to `/home/pi/Documents/` (the code expects that path for the model and the captures):

```
/home/pi/Documents/PoseEstimationJT_Optimized.py
/home/pi/Documents/myDisplayFunctions.py
/home/pi/Documents/scoreboard_link.py
/home/pi/Documents/resources/saved_model_192x256/model_float16_quant.tflite
```

Field captures go to `/home/pi/Documents/FieldCaptures/`, which is created automatically.

## 6. Users, groups and permissions

```bash
sudo usermod -aG gpio,spi,i2c,dialout,bluetooth,video pi
```

* `gpio` / `spi` / `i2c`: the Arduino outputs, OLED and button. `video`: the camera. `dialout`: `/dev/ttyAMA1`. `bluetooth`: BlueZ's D-Bus policy only lets root and this group talk to `bluetoothd`.
* The power button runs `sudo -n /sbin/shutdown -h now`, so `pi` needs passwordless sudo for `shutdown`. Raspberry Pi OS sets up passwordless sudo for the first user by default (`/etc/sudoers.d/010_pi-nopasswd`). If you lock that down, keep at least `pi ALL=(root) NOPASSWD: /sbin/shutdown`.

## 7. Services (start on boot)

```bash
cd <repo>/pi
sudo cp systemd/scoreboard.service systemd/scoreboard-link.service \
        systemd/scoreboard-bt.service systemd/scoreboard-bt.timer /etc/systemd/system/
sudo mkdir -p /etc/systemd/system/scoreboard.service.d
sudo cp systemd/scoreboard.service.d/10-safety.conf /etc/systemd/system/scoreboard.service.d/

# Bluetooth must not start during boot (its firmware upload used to stall boot ~8 s); the timer starts it
sudo systemctl disable hciuart.service bluetooth.service

sudo systemctl daemon-reload
sudo systemctl enable --now scoreboard.service scoreboard-link.service scoreboard-bt.timer
```

Check: `systemctl status scoreboard scoreboard-link scoreboard-bt.timer`. The `[STATUS]` line every 60s in `journalctl -u scoreboard` shows fps (~2.9), the CPU clock and the temperature.

## 8. Boot-time trimming (optional, ~40 s → ~14 s to first frame)

```bash
sudo systemctl disable sshswitch.service apt-daily.timer apt-daily-upgrade.timer \
                       rpi-eeprom-update.service triggerhappy.service triggerhappy.socket
```

**Do not** disable `raspi-config.service` (see step 2).

## 9. Power-cut hardening

* `sudo tune2fs -c 25 /dev/mmcblk0p2`: full filesystem check every 25 boots (adds ~20s on those boots).
* `fsck.repair=yes` in `cmdline.txt` (step 3).
* The code already writes captures atomically and avoids `.pyc` files (`PYTHONDONTWRITEBYTECODE=1` in the drop-in).
* The Pi has no clock battery, so all timing in the code is monotonic, and file names carry a session counter.

## 10. Nice to have

* **Samba + WS-Discovery** (`samba`, `wsdd`) to browse `FieldCaptures` from Windows, and **Syncthing** to pull captures home automatically.
* `avahi-daemon` (installed by default) makes the Pi reachable as `scoreboard-pi.local`.

## 11. Verify end to end

1. `journalctl -u scoreboard -f`: `[STATUS]` lines at ~2.9 fps. The OLED shows the camera view with the net line for 5 minutes.
2. The Arduino says "Pi connected" (heartbeat on pin 46) within a few seconds of the first frame.
3. A T-pose scores. A held cobra subtracts.
4. `journalctl -u scoreboard-link -f`: `UART open`, then about 20s after boot `GATT service registered` and `advertising as "Scoreboard"`.
5. The phone page connects and shows the score.

## Moving to different hardware (V2 notes)

* **Pin numbers** are BCM GPIO numbers in the code (`board.D5`, `D6`, `D19`, `D21`, `D26`, `D13`, `D12`, plus SPI0 CE0 / GPIO 24 / GPIO 25 for the OLED). Any board with the standard 40-pin header and Adafruit Blinka support keeps the harness.
* **UART for the phone link:** on a Pi 4 / CM4 it's `dtoverlay=uart2` (GPIO 0/1, `/dev/ttyAMA1`). A **Pi 5** has different UART overlays (`dtoverlay=uart2-pi5`; device names differ) and doesn't need the Bluetooth/UART juggling, because its Bluetooth isn't on a GPIO UART. Set `SCOREBOARD_LINK_PORT` in `scoreboard-link.service` to the new device. A USB-serial adapter also works (`/dev/ttyUSB0`) if the board has no spare UART.
* **Bluetooth:** `scoreboard_link.py` only needs BlueZ over D-Bus, so it runs on any Linux board with BlueZ. On a board whose Bluetooth doesn't use `hciuart`, replace the `ExecStart` in `scoreboard-bt.service` with `systemctl start bluetooth.service`.
* **A faster board / newer OS:** the vision code runs on newer Python and `tflite-runtime` / `ai-edge-litert` versions. Benchmark `SCOREBOARD_THREADS` again (3 beat 4 on the Pi 4 because the camera threads need a core).
* **Logic levels:** every Pi-side pin is 3.3V. The Mega's TX3 must keep its 5.1k/10k divider on any 3.3V board.
