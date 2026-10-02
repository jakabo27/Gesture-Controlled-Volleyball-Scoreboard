# Raspberry Pi 4: vision engine

Everything here is a copy of what runs on the scoreboard's Pi. The file layout matches `/home/pi/Documents/` on the Pi, so a deploy is a straight copy.

| File | What it is |
|---|---|
| `PoseEstimationJT_Optimized.py` | The whole vision engine: camera stream, two-pass MoveNet inference, T-pose / cobra rules, net-line calibration, keystone estimator, GPIO output, heartbeat, watchdogs, OLED, field capture and pose-event logging |
| `myDisplayFunctions.py` | SSD1351 OLED helper (Adafruit Blinka + `adafruit_rgb_display`) |
| `resources/saved_model_192x256/model_float16_quant.tflite` | MoveNet MultiPose Lightning, 192×256 input, float16 TFLite |
| `systemd/scoreboard.service` (+ `scoreboard.service.d/10-safety.conf`) | The service unit and its drop-in |
| `boot-config.txt` | Snapshot of `/boot/config.txt` as deployed (reference only, see below) |
| `scoreboard_link.py` | **Phone display link (not deployed yet):** reads the Arduino's state over UART and serves it over Bluetooth LE |
| `systemd/scoreboard-link.service`, `scoreboard-bt.service` / `.timer` | Its service, and the timer that starts Bluetooth 20s after boot |

## Hardware

* Raspberry Pi 4 Model B, 2GB
* Wide-angle USB camera (Arducam 1080p low-light WDR module, hardware MJPG), mounted at the net post looking along the net
* Adafruit 1.5" SSD1351 128×128 RGB OLED on SPI0 (CS = CE0, DC = GPIO 25, RST = GPIO 24)
* Power button between GPIO 12 (pin 32) and GND
* Five outputs to the Arduino Mega (see the wiring table in the [main README](../README.md#wiring))

## Software stack

The Pi runs 32-bit Raspbian Buster (Python 3.7, kernel 5.10). These are the versions that are known to work:

| Package | Version |
|---|---|
| `tflite-runtime` | 2.7.0 (PINTO0309's armv7l build with multithreading) |
| `opencv-python` / `opencv-contrib-python` | 4.5.5.62 |
| `numpy` | 1.19.5 |
| `Adafruit-Blinka` | 6.20.1 |
| `adafruit-circuitpython-rgb-display` / `-ssd1351` | 3.10.10 / 1.3.1 |
| `Pillow` | 9.0.0 |

On a desktop (Windows / macOS) the script falls back to `tensorflow.lite`, skips the GPIO and OLED, and shows the annotated view in a window. Pass a video file to run it against a recording:

```bash
python PoseEstimationJT_Optimized.py "path/to/game.mp4"
```

## Install as a service

The complete from-scratch setup (OS, packages, `config.txt`, groups, every unit and the boot chain) is in [`docs/pi-setup-from-scratch.md`](../docs/pi-setup-from-scratch.md). The short version for the vision engine:

```bash
sudo cp systemd/scoreboard.service /etc/systemd/system/
sudo mkdir -p /etc/systemd/system/scoreboard.service.d
sudo cp systemd/scoreboard.service.d/10-safety.conf /etc/systemd/system/scoreboard.service.d/
sudo systemctl daemon-reload
sudo systemctl enable --now scoreboard.service
journalctl -u scoreboard -f
```

* The unit starts after `local-fs.target`, not the network, so it starts at the courts with no Wi-Fi.
* `Restart=always`: the in-process watchdog exits the process if the main loop stalls for 60s, and systemd brings it back.
* The drop-in sets `Nice=10` so SSH, Wi-Fi and Samba always get CPU first, `SCOREBOARD_THREADS=3` (benchmarked faster than 4 because the camera threads need a core), and `PYTHONDONTWRITEBYTECODE=1` (a `.pyc` cut short by a power cut could otherwise break imports).
* The power button handler calls `sudo -n /sbin/shutdown -h now`, so the `pi` user needs passwordless sudo for `shutdown`.
* A `[STATUS]` line every 60s logs the loop time, fps, thread count, net line, keystone fit, CPU temperature and clock.

## Tunables

All at the top of `PoseEstimationJT_Optimized.py`:

| Constant | Value | Meaning |
|---|---|---|
| `POSE_HOLD_FRAMES` / `POSE_WINDOW_FRAMES` | 2 / 3 | T-pose must be seen in 2 of the last 3 frames |
| `COBRA_HOLD_SECONDS` | 0.8 | Cobra hold time (a volleyball *set* looks like a cobra, but for well under a second) |
| `SCORE_COOLDOWN` | 3.0s | Lockout after a point |
| `OVERLAP_MARGIN` | 0.12 | Half-frame overlap around the net line |
| `MAX_CENTER_DRIFT` | 0.07 | Net line clamp, ±7% of frame width |
| `LIMB_CONF_THRESH` | 0.15 | Elbow / wrist keypoint confidence floor (shoulders use 0.20) |
| `MIN_TPOSE_SHOULDER_PX` | 22 | Ignore people further than ~12m away (shoulder width ≈ 270px / distance in m) |
| `HEARTBEAT_PERIOD` | 1.0s | Arduino heartbeat toggle period |
| `SAVE_INTERVAL_SECONDS` | 3.0s | Periodic background capture (~130MB/hour) |
| `POSE_EVENT_LOGGING` | True | 20-before / 6-after annotated bursts for every scored point |

## Field captures

On the Pi everything goes to `/home/pi/Documents/FieldCaptures/`:

* `Periodic/`: one frame every 3s
* `ConfirmedPoses/`: raw + annotated image for every point and cobra (newest 2000 kept)
* `PoseEvents/<session>_<time>_<side>_<TPOSE|COBRA>/`: 27 annotated frames plus `frames.json` with every person's keypoints and every rule value (newest 300 kept)
* `PoseEvents/tpose_candidates.jsonl`: every "arms spread" person in every frame, including near misses (rotated at 50MB)

The whole folder is capped at 5GB (oldest periodic frames go first), and writing stops if the SD card drops below 2GB free. Captures contain people's images, so they're kept out of this repo.

## `/boot/config.txt` notes

`boot-config.txt` is a snapshot, not something to copy blindly. The relevant lines:

* `dtoverlay=disable-bt`: Bluetooth off. This frees the PL011 UART and removes an 8s `hciuart` hang from boot. The planned phone display reverses this (see [`docs/phone-display-plan.md`](../docs/phone-display-plan.md)).
* `initial_turbo=30`, `boot_delay=0`, `disable_splash=1`: faster boot.
* The CPU governor **must** end up `ondemand` (set by `raspi-config.service` on Buster). With it disabled, the Pi sat at 600MHz and the loop took 2.4s instead of 0.34s.

## Phone display link

`scoreboard_link.py` is a separate, lower-priority service that forwards the Arduino's state line (UART2, `/dev/ttyAMA1`, 38400 baud) to a BLE GATT characteristic for the page in [`web/`](../web/). It needs a `config.txt` change and two new wires, so the step-by-step deploy (and rollback) is in [`docs/phone-display-plan.md`](../docs/phone-display-plan.md#deploy-checklist-needs-physical-access).

## The model

`model_float16_quant.tflite` is the float16 TFLite conversion of Google's [MoveNet MultiPose Lightning](https://www.tensorflow.org/hub/tutorials/movenet) (Apache License 2.0), at the 192×256 input size, from [PINTO0309's PINTO_model_zoo](https://github.com/PINTO0309/PINTO_model_zoo). The 192×256 (H×W) input matches the ~1.2:1 aspect of each half-frame, so players are distorted less than with a square input.
