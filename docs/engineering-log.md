# Engineering log: Volleyball Scoreboard 2026

> **About this document.** This is the running engineering log for the 2026 rework, kept in order as the work happened. Early sections were sometimes superseded or corrected by later ones; where the log and the code disagree, the code (and the main README) are right. For the curated overview, see the [main README](../README.md).


**Last Updated:** October 2026  
**Primary Target Platform:** **Raspberry Pi 4 Model B (Rev 1.5, 2GB LPDDR4, Quad-Core Cortex-A72 @ 1.8GHz)** with USB Webcam, Adafruit SSD1351 RGB OLED display, and custom Arduino MEGA LED Scoreboard Controller *(Note: Hardware confirmed via live SSH query `cat /proc/device-tree/model` — existing scoreboard is already running a Pi 4!)*  
**Secondary Platform:** Windows 10/11 x64 Development & Video Simulation Rig  

---

## 1. Executive Summary & Core Objective

The automated volleyball scoreboard system uses a wide-angle USB webcam mounted near the net pole under the net, looking across the court.
- **Court Left:** Monitored as the **Home Team**.
- **Court Right:** Monitored as the **Away Team**.
- **T-Pose Gesture:** When any active player faces the camera and holds a T-pose for 2 consecutive frames, a point is awarded to that player's side.
- **Surrender Cobra Gesture:** When a player puts their hands on top of their head with elbows flared out, a point is subtracted from that side (undo).
- **Arduino Signaling:** The Pi outputs 50ms active-high pulses to an Arduino controller (Home Point, Away Point, Home Subtract, Away Subtract, and Heartbeat).
- **Auditory & Visual Feedback:** The Arduino plays WAV sound effects via an SD card and 8-bit DAC (`PtHm.wav`, `PtAwy.wav`, `SurHo.wav`, `SurAw.wav`, `PiCon.wav`, `PiDis.wav`), drives 252 WS2812B RGB LEDs, and displays scores on large 7-segment digits.

---

## 2. 12-Player Capacity: Dual-Half with +12% Overlap Margin Architecture

### Why Single-Pass Fails in 6v6 Volleyball
MoveNet MultiPose has a hard architectural output limit of **6 people maximum**.
In standard 6-vs-6 volleyball:
$$\text{6 players on Left Team} + \text{6 players on Right Team} = \text{12 active players on the court!}$$

If MoveNet MultiPose runs across the entire frame in a single pass, it will select the 6 most prominent people in the camera's view (typically front-row players near the net). If a **back-row player** on either team steps back and performs a T-pose, they would be person #7 or #8 in prominence and **completely omitted from the model's output tensor**!

### The Dual-Half Architecture with +12% Overlap Margin (The 12-Player Solution)
By dynamically splitting the frame into a Left Half and a Right Half at the net line:
- **Left Half Inference:** Slices from $x = 0$ to $x = \text{Center}_x + 0.12$ (allocates MoveNet's full 6-person capacity exclusively to the **Home Team**).
- **Right Half Inference:** Slices from $x = \text{Center}_x - 0.12$ to $x = 1.0$ (allocates MoveNet's full 6-person capacity exclusively to the **Away Team**).
- **Reaching Across the Net (Solved):** The $+12\%$ overlap margin ensures that an outstretched arm reaching across the net line into the opponent's side is **never clipped or truncated** out of the frame! MoveNet detects all 17 keypoints (shoulder, elbow, wrist) with high confidence.
- **Torso-Centroid Attribution:** Team assignment is decided by the player's **torso centroid** (midpoint of shoulders and hips). Even if a Home player's wrist extends to $x = 0.55$, their torso is at $x = 0.44 < \text{Center}_x$, correctly attributing the point to Home.
- **Total Tracked Players:** **Up to 12 players simultaneously**, guaranteeing that back-row players are never dropped.
- **Performance on Pi 4 (measured Oct 1 2026, 192×256 model, 1.75 GHz):** **~340 ms per loop (~2.9 fps)** with 3 inference threads as a service. Benchmark: 3 threads 408 ms vs 4 threads 495 ms (4 threads competes with the camera/capture threads). Before the governor fix the CPU was stuck at 600 MHz and loops took ~2.4 s. A 2-frame T-pose therefore confirms in ~0.7 s.

---

## 3. Safe Auto-Calibration with Strict Safety Clamps

To prevent an auto-calibrating net line from drifting or destabilizing games:

```
[ Team Left (Home) ]      <--- Safe Drift Window --->      [ Team Right (Away) ]
                                |  Nominal Net  |
0.0                           0.45    0.50    0.55                         1.0 (X)
```

1. **Strict Safety Bounds (The "Safety Clamp"):**
   The net center line is strictly clamped to $\pm 7\%$ (`MAX_CENTER_DRIFT = 0.07`) from the nominal center $0.50$:
   $$\text{Center}_x \in [0.43, 0.57]$$
   Even if an entire team gathers on one side during a timeout, the net line can **never** drift beyond 0.57 or 0.43. *Caveat:* the calibrator measures the midpoint between the two teams' median positions, not the net itself; in field frames the real pole sits anywhere from x≈0.49 to 0.57 depending on the venue (see Section 20 for the pole-detection plan).
2. **Upright-Only Calibration Filtering:**
   - Auto-calibration only processes **standing upright players** ($\text{Hip}_y - \text{Shoulder}_y > 0.15 \times$ frame height, in pixels). Bent-over players, players diving for balls, or players picking up volleyballs are **completely excluded** from calibration calculations.
   - Evaluates quality-filtered candidate frames over a **30-second window** (10s before first point).
   - If the candidate median shifts by more than $1.5\%$, it updates smoothly via Exponential Moving Average (EMA):
     $$\text{Center}_x \leftarrow 0.70 \times \text{Center}_x + 0.30 \times \text{ClampedCandidate}$$
   - If no drift is detected, the line remains locked.

---

## 4. Local Field Capture Engine & 5GB Storage Buffer

To enable post-match analysis of false positives and detection accuracy, `PoseEstimationJT_Optimized.py` includes a local offline capture system:

### Capture Behavior
1. **Background Dataset:** Saves **one frame every 0.75 s** (`SAVE_INTERVAL_SECONDS`) via a background writer thread (`AsyncCaptureSaver`) to `/home/pi/Documents/FieldCaptures/Periodic/`.
2. **Confirmed Detections:** Saves **every confirmed T-pose and Surrender Cobra** to `/home/pi/Documents/FieldCaptures/ConfirmedPoses/` (saving both the clean raw image and the annotated debug skeleton image).
3. **100% Offline:** Operates entirely locally at the court with zero network dependency. When brought home, images can be pulled via Syncthing, SCP, or Samba.

### Storage Capacity & 5GB Cap
- Frames are saved at full camera resolution ($1280 \times 720$), $\sim 170\text{ KB}$ each in daylight; see Section 19 for the storage math ($\approx 0.8\text{ GB/hour}$).
- **Enforcing the 5.0 GB Limit:**
  `AsyncCaptureSaver` recalculates directory size every 150 saves (on the writer thread). If total usage exceeds 5.0 GB, it performs an automatic FIFO purge of the oldest 250 periodic background frames while **preserving all confirmed T-pose/Cobra captures**.
  Additionally, it checks `shutil.disk_usage('/')` and immediately halts writing if free space drops below 2.0 GB, protecting the operating system.

---

## 5. Arduino Code Review & Critical Heartbeat Discovery

Inspecting `ScoreboardVolleyballChangeWinning.ino` revealed a vital timing constraint:

### The `thisHeartbeatPeriod > 300` Constraint (Line 471)
```cpp
if ( ((thisHeartbeatPeriod < prevHeartbeatPeriod1 + heartbeatRange &&
      thisHeartbeatPeriod > prevHeartbeatPeriod1 - heartbeatRange) &&
     (thisHeartbeatPeriod < prevHeartbeatPeriod2 + heartbeatRange &&
      thisHeartbeatPeriod > prevHeartbeatPeriod2 - heartbeatRange) &&
      thisHeartbeatPeriod > 300) || justPlayedWinningTune > 0)
```
- **The Issue:** The Arduino expects the heartbeat toggle interval to be **greater than 300 milliseconds**. If the Pi loop executes faster than 3.3 FPS and toggles the heartbeat pin every frame, the Arduino flags `raspiOn = 0` (disconnected), plays `PiDis.wav`, and **refuses to register score pulses** from `PiPinHome` and `PiPinAway`.
- **The Solution:** In `PoseEstimationJT_Optimized.py`, we added a heartbeat throttle:
  ```python
  if (t - last_heartbeat_time) >= 0.35: # 350ms period
      heartbeat_val = 1 - heartbeat_val
      heartbeatPin.value = heartbeat_val
      last_heartbeat_time = t
  ```
  **Superseded:** the heartbeat is now toggled by a dedicated `HeartbeatThread` at a steady **1.0 s** period (measured 982–1020 ms), while the main loop has processed a live camera frame within the last 20 s (`CAMERA_OUTAGE_GRACE`; a USB camera re-connect takes ~11 s, so brief camera drop-outs no longer make the Arduino play disconnect/connect). A main-loop toggle made the period depend on frame time; 1.0 s is accepted by the original firmware, the fixed firmware, and the intermediate `unsigned long` firmware alike.

---

## 6. Root Causes & Fixes for Pi Crashes

### Bug 1: The > 6 People Crash / Array Dimension Collapse
* **Root Cause in `PoseEstimationJT.py`:**
  ```python
  keypoints_with_scores = np.squeeze(interpreter.get_tensor(output_details[0]['index']))
  ```
  When MoveNet detects a single person, `np.squeeze()` collapses `(1, 1, 56)` into `(56,)`. Iterating over `(56,)` loops over 56 float numbers, causing `keypoints_with_score[(index * 3) + 1]` to throw an unhandled `TypeError: 'numpy.float32' object is not subscriptable`.
* **Fix Applied:**
  Explicit dimension normalization handles 1D, 2D, and 3D shapes. Detections are sorted by confidence score (`bbox_score`) descending and clamped. Bounding boxes are clamped to `[0.0, 1.0]`.

### Bug 2: The 2,600+ `acos` Math Domain Exceptions
* **Root Cause in `myImageFunctions.py`:**
  ```python
  Rangle = degrees(acos((Rlen1**2 + Rlen2**2 - Rlen3**2) / (2 * Rlen1 * Rlen2)))
  ```
  Floating-point rounding errors produced ratios like `1.0000000000000002`. Python's `math.acos()` immediately throws `ValueError: math domain error` if the argument is outside $[-1.0, 1.0]$.
* **Fix Applied:**
  Guarded by `max(-1.0, min(1.0, ratio))` and epsilon checks (`Rlen1 > 1e-4`), eliminating all 2,600+ exceptions recorded in `LoggingImageFunctionsFile.log`.

---

## 7. Fast 2-Frame Pose Confirmation (Snappy Scoring)

Per user request, the confirmation threshold uses a **2-consecutive-frame requirement** (`POSE_HOLD_FRAMES = 2`):
- At ~3.5 FPS dual-pass on the Pi, 2 frames equals **~560ms** of deliberate holding.
- Scoring registers immediately and reliably.

*All geometry runs in true pixel coordinates (Section 18); tolerances scale with shoulder width.*

**Confirmation (Oct 1 update):** a T-pose scores when it is seen in **2 of the last 3** processed frames (`POSE_HOLD_FRAMES` / `POSE_WINDOW_FRAMES`), not 2 in a row: in field tests a single frame with a flickering wrist confidence (0.19 vs a 0.20 cutoff) reset the hold, so users had to hold ~3 s. Elbow/wrist confidence floor is 0.15 (`LIMB_CONF_THRESH`), shoulders 0.20. Re-arming after a point needs 3 frames in a row without a T-pose.

### T-Pose Geometry
- **Height Alignment:** Shoulders, elbows, and wrists all within $Y_{tol} = \max(14\text{ px}, 0.35 \times \text{ShoulderWidth})$ of shoulder height.
- **Horizontal Ordering:** $\text{RightWrist}_x < \text{RightElbow}_x < \text{RightShoulder}_x < \text{LeftShoulder}_x < \text{LeftElbow}_x < \text{LeftWrist}_x$.
- **Wingspan Ratio:** $\text{Wrist-to-Wrist Distance} \ge 1.85\times \text{Shoulder Width}$ (scales to $1.60\times$ at extreme sidelines).
- **Minimum Size:** shoulder width 22–550 px.
- **Straight Arms:** Elbow joint angles $\ge 135^\circ$.
- **Tilt Compensation Cap:** Spine lean capped to $|dx/dy| \le 0.21$ ($\approx 12^\circ$), and arm perpendicularity checked to $70^\circ-110^\circ$ ($90^\circ \pm 20^\circ$). The tighter 3° / ±15° limits rejected 2 of 5 real field T-poses, because wide-angle distortion makes upright players near the frame edges lean 4–6°.
- **Re-arm:** after scoring, a side must show a frame without the gesture before that gesture can score again (one long hold = one point).

### Surrender Cobra Geometry
- **Hold Time:** must be held $\ge 0.8$ s (`COBRA_HOLD_SECONDS`); a volleyball *set* looks like a cobra but lasts well under a second.
- **Head Elevation:** Wrists at or above eye level ($\text{Wrist}_y \le \text{EyeTop}_y + 0.08 \times \text{ShoulderWidth}$).
- **Head Centerline Closeness:** $|\text{Wrist}_x - \text{Nose}_x| \le 0.75 \times \text{ShoulderWidth}$ and $|\text{LeftWrist}_x - \text{RightWrist}_x| \le 1.2 \times \text{ShoulderWidth}$ (measured: real hands-on-head wrists are ~0.5 and ~0.9–1.0 shoulder widths).
- **Flared Elbows:** Elbows abducted wider than shoulders with acute angles ($35^\circ - 100^\circ$).

---

## 8. Raspberry Pi Autostart & Storage Paths

* **Autostart:** now `scoreboard.service` (systemd, Section 21). The old `/etc/xdg/autostart/myapp.desktop` was renamed to `myapp.desktop.bak` so only one instance runs.
* **Test Photos on Pi:**
  - `/home/pi/Documents/Syncme/`
  - `/home/pi/Documents/Syncme/NoTpose/`
* **Deployed Scripts on the Pi:**
  - `/home/pi/Documents/PoseEstimationJT_original_backup.py`: Safe, unmodified backup of the original script.
  - `/home/pi/Documents/myImageFunctions.py`: Updated with math domain & zero-division fixes.
  - `/home/pi/Documents/PoseEstimationJT_Optimized.py`: Clean, production-ready script featuring 12-player dual-pass inference with +12% overlap, bounded auto-calibration with upright filtering, fast 2-frame pose hold, Arduino heartbeat throttling, and 5GB local capture engine.

---

## 9. Handling Court Realities: Camera Tilt on Sand & Wide-Angle Distortion

Three visual SVG diagrams have been created in the project directory for reference:
- [`court-net-line.svg`](../media/diagrams/court-net-line.svg): Illustrates the court perspective from under the net pole, the nominal 0.50 dividing line, the $\pm 5\%$ drift safety window $[0.45, 0.55]$, and how torso-centroid attribution allows arms to reach across the net tape without triggering the wrong team.
- [`tpose-acceptance-envelope.svg`](../media/diagrams/tpose-acceptance-envelope.svg): Illustrates the anatomical acceptance envelope (shoulder height alignment $\pm 10\%$, elbow straightness $\ge 135^\circ$, wingspan ratio $\ge 1.9\times$, and strict horizontal joint ordering).
- [`camera-tilt-and-wide-angle.svg`](../media/diagrams/camera-tilt-and-wide-angle.svg): Illustrates the two critical outdoor court challenges and their mathematical solutions:

### A. Uneven Sand Roll Tilt Solution: Torso-Relative Spine Coordinates (Capped to 5%)
* **The Problem:** In sand volleyball, the tripod often rests on uneven sand, causing the camera to be tilted by a few degrees. In a naive pixel-grid coordinate check, an upright player holding level arms will appear tilted in image coordinates, falsely failing horizontal alignment.
* **The Solution:** We calculate the player's anatomical spine vector $\vec{V}_{\text{spine}}$ from their hip midpoint to their shoulder midpoint. We evaluate arm angles **relative to the player's spine** (requiring arms to be $90^\circ \pm 15^\circ$ perpendicular to the torso). Tilt compensation is capped to **5% slope** ($|dx/dy| \le 0.055$), so extreme lateral leaning is rejected.

### B. Wide-Angle Camera Sideline Adaptation
* **The Problem:** Wide-angle lenses ($110^\circ - 120^\circ$ FOV) introduce perspective foreshortening for players standing on the extreme sidelines ($x < 0.20$ or $x > 0.80$). Because they are viewed at a steep angle, their arms extend partially along the camera's Z-axis (towards or away from the lens), causing their visible 2D wingspan to appear up to 15% shorter.
* **The Solution:** The required wingspan ratio dynamically scales based on the player's distance from the court center:
  - Center Court ($0.25 < x < 0.75$): Standard $\ge 1.90\times$ shoulder width.
  - Sidelines ($x < 0.20$ or $x > 0.80$): Adaptively scales down to $\ge 1.65\times$.
  - Elbow straightness ($\ge 135^\circ$) remains strict everywhere to maintain zero false positives.

---

## 10. 2v2, 4v4, and 6v6 Match Compatibility

The dual-half processing architecture dynamically handles varying team sizes:
- **Capacity:** Each half supports from **1 player up to 6 players**.
- **2v2 Beach Doubles:** Tracks 2 players on Home and 2 players on Away.
- **6v6 Indoor / Sand:** Tracks 6 players on Home and 6 players on Away (all 12 players simultaneously).
- **Calibrator Adaptability:** The auto-calibrator only requires $\ge 1$ detected player on each side to evaluate court drift, ensuring full functionality during 2v2 doubles.

---

## 11. Arduino Scoreboard Firmware Fix (`Arduino_Scoreboard_Fixed/`)

A dedicated copy of the Arduino controller firmware was created at:
`Volleyball Scoreboard 2026/Arduino_Scoreboard_Fixed/ScoreboardVolleyballChangeWinning.ino`

### Fix Implemented (Line 471):
- **Lowered Heartbeat Minimum Period:** Changed from `thisHeartbeatPeriod > 300` to `thisHeartbeatPeriod > 75`. This enables the Pi to run anywhere from 1.5 FPS up to 13 FPS without triggering a false disconnection.
- **Instant Boot Connection:** Added an initial boot bypass: if `prevHeartbeatPeriod1 >= 3000` (uncalibrated boot state), the Arduino accepts the very first valid heartbeat pulse immediately rather than requiring multiple cycles to calibrate historical periods.
- **Irregular-Pulse Debounce:** requires 3 consecutive irregular heartbeat periods before declaring the Pi disconnected.
- **Signed 32-bit Heartbeat Periods:** `thisHeartbeatPeriod`, `prevHeartbeatPeriod1/2` and `heartbeatRange` are `long`. (An intermediate version used `unsigned long`, which made `prevHeartbeatPeriod1 - heartbeatRange` wrap to ~4 billion for any period under 700 ms, so the periods never matched and the Pi was declared disconnected ~7 s after connecting.)
- **Must be re-flashed** to the Mega for these fixes to take effect. Python's 350 ms heartbeat throttle alone also satisfies the original firmware's `> 300` check.

---

## 12. Hardware Swap Evaluation: Pi 4 Already Installed!

During the live SSH query to the scoreboard hardware (`cat /proc/device-tree/model` and `lscpu`), we confirmed:
```
Model: Raspberry Pi 4 Model B Rev 1.5
CPU: 4x Cortex-A72 @ 1.8 GHz
RAM: 2GB LPDDR4 (1820 MB reported, ~1.4GB free)
OS: Linux scoreboard32 5.10.63-v7l+ armv7l
```

### Discovery: No Hardware Swap Required!
You **already have the Raspberry Pi 4 (2GB)** inside your scoreboard!
You do **not** need to do a swap:
1. **You have the full 4× Cortex-A72 cores running at up to 1.8 GHz.**
2. **Frame rate is not yet measured at full clock** (see Sections 2 and 22). The OS is 32-bit Raspbian Buster (armv7l, Python 3.7, tflite-runtime 2.7); a 64-bit OS would allow faster inference and newer models.
3. **The Orange Pi 4 LTS is definitively NOT needed or recommended:** The Orange Pi only has two A72 cores (slower than your four A72 cores), lacks drop-in pinout compatibility, and would break your Adafruit Blinka/OLED drivers. You already possess the ideal board for this project!

---

## 13. Pi-to-Arduino Hardware Wiring Table

Refer to the visual diagram: [`wiring-pi-to-arduino.svg`](../media/diagrams/wiring-pi-to-arduino.svg)

| Signal Description | Raspberry Pi 3B+ / 4 Pin # | BCM GPIO Number | Arduino MEGA 2560 Pin | Wire Color / Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Away Up (+1)** | **Pin 29** | `GPIO 5` (`board.D5`) | **Pin 47** (`PiPinAway`) | Active-High 50ms pulse |
| **Home Up (+1)** | **Pin 31** | `GPIO 6` (`board.D6`) | **Pin 45** (`PiPinHome`) | Active-High 50ms pulse |
| **Home Cobra (-1)** | **Pin 35** | `GPIO 19` (`board.D19`) | **Pin 42** (`PiPinSurrenderHome`) | **Orange Skinny Wire** |
| **Away Cobra (-1)** | **Pin 40** | `GPIO 21` (`board.D21`) | **Pin 43** (`PiPinSurrenderAway`) | **Yellow Skinny Wire** |
| **Heartbeat Alive** | **Pin 37** | `GPIO 26` (`board.D26`) | **Pin 46** (`PiPinHeartbeat`) | Green wire; toggles every 350ms |
| **Spare Auxiliary** | **Pin 33** | `GPIO 13` (`board.D13`) | **Pin 44** (`PiSparePin`) | Gray wire; reserved |
| **Common Ground** | **Pin 39** (or 6, 9, 14, 20) | `GND` | **GND** (Power Header) | **MANDATORY common ground** |
| **Power Button** | **Pin 32** | `GPIO 12` (`board.D12`) | *N/A (Local to Pi)* | Pushbutton to Pi GND (hold 10 counts to shutdown) |
| **OLED CS** | **Pin 24** | `CE0 / GPIO 8` | *N/A (Local to Pi)* | Adafruit SSD1351 SPI Chip Select |
| **OLED DC / RESET** | **Pins 22 & 18** | `GPIO 25 & GPIO 24` | *N/A (Local to Pi)* | Data/Command & Hardware Reset |
| **OLED SPI MOSI/SCLK** | **Pins 19 & 23** | `MOSI & SCLK` | *N/A (Local to Pi)* | Hardware SPI Master Out & Clock |

---

## 14. SBC Comparison: Installed Raspberry Pi 4 vs. Youyeetoo R1 / Mekotronics R58 (RK3588S)

| Specification / Capability | Current Installed Board: Raspberry Pi 4 (2GB) | Alternative: Youyeetoo R1 / Mekotronics R58 (RK3588S) |
| :--- | :--- | :--- |
| **SoC / Architecture** | Broadcom BCM2711: 4× Cortex-A72 @ 1.8 GHz | Rockchip RK3588S: 4× Cortex-A76 @ 2.4 GHz + 4× Cortex-A55 @ 1.8 GHz |
| **NPU Acceleration** | None (Runs MoveNet via CPU XNNPACK delegate) | **6.0 TOPS Tri-Core NPU (Requires Rockchip RKNN toolkit)** |
| **MoveNet Inference Latency** | Unmeasured (see Section 2) | **~15ms CPU / ~5ms NPU (60+ FPS if converted to RKNN)** |
| **Power Requirements** | **5V @ 1.5A–2.5A (~7.5W–12W)** (Standard USB-C power bank!) | **12V @ 2A–3A DC (~15W–25W)** (Requires 12V barrel jack or 12V PD trigger) |
| **GPIO Pinout Compatibility** | **100% Standard 40-Pin Header** (Matches existing wiring harness) | ⚠️ **Non-standard Rockchip pinout** (Requires rewiring and remapping) |
| **OLED Display Driver** | **Native Adafruit Blinka + SSD1351 SPI** | ⚠️ **Broken / Unsupported** (Requires writing custom SPI driver) |
| **Software Migration Cost** | **0 hours (Already deployed and working)** | **15–25 hours** (C/Python driver rewrites, kernel overlays) |
| **Practical Court Benefit** | **Human reaction time is ~200ms; scoring triggers in ~220ms** | Running at 60 FPS provides zero perceptible benefit to players |
| **Verdict** | **KEEP IN SCOREBOARD (Optimal balance of power and compatibility)** | **DO NOT USE (Overkill, power-hungry, breaks wiring & OLED)** |

---

## 15. Pose Hold Timing: Before vs. After Comparison Table

| Metric / Parameter | Original Pi Code (`PoseEstimationJT.py`) | New Production Code (`PoseEstimationJT_Optimized.py`) | Impact & Analysis |
| :--- | :--- | :--- | :--- |
| **Court Coverage** | Left half, then right half (right skipped if a left T-pose was found) | Dual-half with +12% overlap (Tracks up to 12 players simultaneously) | Complete 6v6 coverage |
| **Model Passes per Loop** | 1 pass (or 2 if pose candidate detected) | 2 half-passes (Left Team + Right Team) | Guarantees all players tracked |
| **Pi 4 Loop Time** | Not measured | ~2.4 s measured at 600 MHz (governor bug); re-measure at full clock | — |
| **Verification Strategy** | **2 Consecutive Frames** (Frame 1 detect $\rightarrow$ immediate re-read $\rightarrow$ Frame 2 verify) | **2 Consecutive Frames** (`POSE_HOLD_FRAMES = 2` across loop iterations) | **Exact same 2-frame requirement!** |
| **Time Required to Score** | Not measured | 2 loop iterations (re-measure after governor fix) | — |
| **False Positive Protection** | High risk: naive slope check, no elbow check, crashed on 1-person | **Extremely Strict**: $\ge 135^\circ$ elbow straightness, spine angle, 10% height band | Celebration arm flailing rejected! |
| **Score Lockout Cooldown** | 3.0s photo save throttle, but no score pin lockout | **3.0s score cooldown** (`SCORE_COOLDOWN = 3.0s`) | Prevents double-triggering |

---

## 16. Aspect Ratio & Vertical Cropping Analysis

1. **How MoveNet Handles Aspect Ratios:**
   - MoveNet MultiPose is trained on square ($256 \times 256$) inputs.
   - In a 16:9 full frame ($1280 \times 720$), squashing the entire court into $256 \times 256$ distorts players horizontally by $1.77\times$.
   - **Why Dual-Half Slicing is Mathematically Superior:**
     With dual-half slicing and +12% overlap, each half slice is $\approx 794 \times 648\text{ px}$ (aspect $\approx 1.22:1$).
     The production model is the **192×256** (H×W, aspect 1.33:1) MoveNet MultiPose build, so the residual horizontal distortion is under 10%.
2. **Why Fixed Vertical Bounds are Preferred Over Dynamic Auto-Crop:**
   - Dynamic auto-cropping (adjusting top/bottom based on player head/feet) causes frame-to-frame jitter.
   - When front-row players jump for a spike or block, their hands extend to the upper edge of the frame; dynamic cropping risks clipping their hands mid-motion.
   - The code currently uses a fixed 2% top cut and 8% bottom cut. Field frames show ~25–30% of the frame is sky, so a tighter fixed top cut would give players more pixels at the model input; evaluate on FieldCaptures.

---

## 17. Dedicated Camera Engine: `CourtCameraStream`

Replaced the generic `imutils.video.VideoStream` with `CourtCameraStream`:
1. **Threaded Zero-Lag Grabber:** Background thread constantly pulls frames with `cap.read()`, eliminating the 4-frame OpenCV V4L2 queue and saving 150–200ms of display latency.
2. **Hardware MJPG Codec:** Automatically requests `CAP_PROP_FOURCC = 'MJPG'`, preventing USB 2.0 bus congestion from uncompressed YUYV streams.
3. **Buffer Cap:** `CAP_PROP_BUFFERSIZE = 1`.
4. **Auto-Reconnect Watchdog:** If the USB camera resets or overheats under intense sun, the stream automatically re-initializes without crashing the scoreboard loop. The camera is opened via its udev path `/dev/v4l/by-id/*-video-index0`, **not index 0**: on Oct 1 the camera dropped off USB 3 times during boot and came back as `/dev/video1`, while the old code kept retrying `/dev/video0` forever and served the last frame (the scoreboard was frozen on its boot-time image). Verified fix: software USB unplug/replug (`/sys/bus/usb/drivers/usb/unbind` + `bind`) recovers automatically in ~12 s.\n4b. **Hung-Camera Check:** if the camera keeps returning bit-identical (non-black) frames for 5 s, it is re-opened.
5. **Stale-Frame Guard:** `read()` returns `None` if the newest frame is older than 2 s, so a dead camera stops the loop (and the heartbeat, so the Arduino reports the Pi disconnected) instead of re-scoring a frozen frame.
6. **Note:** the grabber thread decodes every frame at 30 fps even though the loop uses far fewer; compare `NUM_THREADS = 3` vs `4` once the governor is fixed.

---

## 18. True Isotropic Pixel-Space Geometry Engine

All keypoint geometric calculations are performed in **sensor pixel coordinates** $(X_{px}, Y_{px})$:
$$X_{px} = X_{norm} \times \text{Width}_{px}$$
$$Y_{px} = Y_{norm} \times \text{Height}_{px}$$

### Why This Fixes Angle Math
Previously, normalized coordinates were used directly where $X \in [0, 1]$ mapped to 1280 px and $Y \in [0, 1]$ mapped to 540 px, introducing a $2.37\times$ vertical coordinate stretch.
* **Elbow Angles:** In pixel space, dot products compute physical sensor angles. A straight arm ($\approx 160^\circ–180^\circ$) now easily clears the $\ge 135^\circ$ elbow threshold, whereas in stretched space it falsely evaluated to $129^\circ$.
* **Surrender Cobra Elbows:** Acute elbow angles now evaluate correctly between $35^\circ$ and $100^\circ$.
* **Adaptive Dynamic Tolerances:** Height tolerance $Y_{tol}$ is now computed relative to shoulder width:
  $$Y_{tol} = \max(14.0\text{ px}, 0.35 \times \text{ShoulderWidth}_{px})$$
  This automatically expands tolerance for close players (who have large 200–400px shoulders) while keeping tolerances tight for back-row players (25–35px shoulders).

---

## 19. Storage Math: 4+ Hours of Match Recording in 5GB

* **Tournament Target Duration:** 4 hours ($14,400\text{ seconds}$).
* **Usable Storage Buffer:** 4.5 GB ($4,608\text{ MB}$, reserving 500 MB for confirmed poses and system logs).
* **Average JPEG Frame Size:** At $1280 \times 640$ (JPEG Quality 80), each frame is $\approx 160–180\text{ KB}$ ($0.17\text{ MB}$).
* **Total Frame Capacity:**
  $$\frac{4,608\text{ MB}}{0.17\text{ MB/frame}} \approx 27,100\text{ frames}$$
* **Configured Save Interval (`SAVE_INTERVAL_SECONDS = 0.75s`):**
  $$\text{Total Frames Saved in 4 Hours} = \frac{14,400\text{ s}}{0.75\text{ s}} = 19,200\text{ frames}$$
  $$19,200\text{ frames} \times 0.17\text{ MB} \approx \mathbf{3.26\text{ GB}}$$
* **Result:** At an interval of **one frame every 0.75 seconds**, an entire 4-hour tournament consumes approximately 3.3 GB, leaving ample headroom below the 5.0 GB limit with zero risk of running out of space.

---

## 20. Optical Net Pole Detection Architecture (Roadmap for Field Frames)

Once real tournament test frames are collected in `/home/pi/Documents/FieldCaptures/`, a dedicated optical net pole locator will be integrated:
1. **Vertical Edge Filtering (Sobel-X):** In beach volleyball, net poles are strong vertical boundaries (red, silver, white, or padded). Applying a vertical Sobel filter ($ksize=5$) and thresholding highlights vertical edges.
2. **Hough Line Transform:** Detects prominent vertical lines with slope $|\theta - 90^\circ| \le 5^\circ$ spanning $>40\%$ of image height.
3. **Pole Center Determination:** Clusters detected vertical lines in the central zone $x \in [0.43, 0.58]$. The centroid of this cluster locks the net dividing line directly onto the physical net pole rather than relying on player centroid distributions.

---

## 21. Production Systemd Service: `scoreboard.service`

The scoreboard now runs under systemd with auto-restart:
* **Service Name:** `scoreboard.service`
* **Restart Policy:** `Restart=always`, `RestartSec=2`
* **Runs as `User=pi` without a desktop session**, so polkit denies a plain `shutdown`; the power-button handler therefore calls `sudo -n /sbin/shutdown -h now` (pi has passwordless sudo).
* **Status Query:** `sudo systemctl status scoreboard.service`
* **Live Logs:** `journalctl -u scoreboard.service -f`
* **Network Share:** the `FieldCaptures` and docs folders are shared via Samba and WS-Discovery.

---

## 22. Fast-Boot Optimization Benchmarks & Hardware Tuning (Sub-5s Startup)

To ensure the scoreboard turns on and begins tracking players almost immediately when powered on at the court:

### 1. Root-Cause Analysis (`systemd-analyze blame`)
Before optimization, the Pi 4 was taking **over 40 seconds** to boot and initialize pose estimation:
1. **Low-Clock Early Boot:** The BCM2711 ARM cores started at a throttled 600 MHz power-saving frequency until the `cpufreq` governor initialized late in userspace, slowing kernel module loading and Python byte-compilation by 2.5×–3×.
2. **`hciuart.service` (8.003s):** Attempted to probe and attach the Bluetooth modem over serial UART at boot, blocking `multi-user.target`.
3. **`sshswitch.service` (2.940s):** Legacy first-boot check for `/boot/ssh` (redundant since `ssh.service` is permanently enabled).
4. **`apt-daily` & `apt-daily-upgrade` (3.409s):** Random SD card reads/writes indexing Debian repositories at boot.
5. **`raspi-config.service` (1.885s):** ⚠️ **Misdiagnosed.** On Buster this service switches the CPU governor from the kernel default `powersave` to `ondemand`. Disabling it left all four cores stuck at **600 MHz** (confirmed Oct 1: `scaling_governor=powersave`, `measure_clock arm` = 600 MHz under full load). **Re-enable it, or set the governor elsewhere** (e.g. `ExecStartPre=+/bin/sh -c 'for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do echo ondemand > $g; done'` in `scoreboard.service`).
6. **`rpi-eeprom-update.service` (1.772s):** Online bootloader update check (stalls when offline at volleyball courts).
7. **`triggerhappy.service` (0.769s):** Hotkey daemon for multimedia keyboards.
8. **Network Dependency:** `scoreboard.service` previously had `After=network.target`, delaying startup when no Wi-Fi was present.

### 2. Optimizations Applied
* **/boot/config.txt Tuning:**
  - `initial_turbo=30`: Forces maximum CPU clock (1,750 MHz) for the first 30 seconds of boot only; after that the governor decides (see the `raspi-config.service` warning above).
  - `boot_delay=0`: Removes the default 1-second firmware display wait.
  - `disable_splash=1`: Skips rendering the rainbow splash screen.
  - `dtoverlay=disable-bt`: Disables Bluetooth modem hardware, freeing UART and permanently eliminating the 8-second `hciuart` hang.
* **Systemd Service Streamlining:**
  - Disabled `hciuart.service`, `bluetooth.service`, `sshswitch.service`, `apt-daily.timer`, `apt-daily-upgrade.timer`, `apt-daily.service`, `apt-daily-upgrade.service`, `rpi-eeprom-update.service`, `raspi-config.service` (**mistake, see above**), `triggerhappy.service`, `triggerhappy.socket`.
* **Network-Independent Service Architecture:**
  - Changed `scoreboard.service` dependencies to `After=local-fs.target` and `Wants=local-fs.target` with `Environment=PYTHONUNBUFFERED=1`. The pose estimation engine starts immediately once local filesystems mount, without waiting for network or desktop daemons.

### 3. Before vs. After Benchmark Results (`systemd-analyze`)

| Metric | Before Optimization | After Optimization | Improvement |
| :--- | :--- | :--- | :--- |
| **Kernel Boot Time** | `8.726s` | **`1.365s`** | **-84.4% (6.4× faster)** |
| **Scoreboard Service Launch** | `@23.5s` (after multi-user) | **`@3.013s`** (after sysinit) | **-87.2% (7.8× faster)** |
| **Total Time to Camera Inference** | `~40–45s` | **`~5.5–6.0s`** | **~7× faster power-on readiness** |
| **Bluetooth Initialization Delay** | `8.003s` | **`0.000s` (Disabled)** | Eliminated |
| **Offline Independence** | Waited on network | **Instant offline launch** | Zero timeout delays |

---

## 23. Remote-Safety, Power Button & OLED Burn-In Protection

The Pi is hard to reach physically, so nothing may leave it unreachable over Wi-Fi.

* **No `/boot/config.txt` changes** for performance work (an earlier overclock caused a crash loop). The CPU speed fix only restores the stock `raspi-config.service` (sets the `ondemand` governor at boot).
* **`Nice=10`** for `scoreboard.service` (systemd drop-in `scoreboard.service.d/10-safety.conf`), so `sshd`, `wpa_supplicant` and Samba always get CPU before pose estimation, whatever `NUM_THREADS` is.
* **Thread count** is set without editing code: `Environment=SCOREBOARD_THREADS=3` in the drop-in (3 benchmarked faster than 4).
* **Power button:** short press wakes the OLED; holding for **5 s** (time-based, not frame-based) shuts down via `sudo -n /sbin/shutdown -h now`. If the button already reads pressed when the script starts (stuck or shorted button), it is ignored until it is seen released, so a bad button can never shut the Pi down on every boot.
* **OLED burn-in:** the panel is blanked except for: the first **5 min** after start (aim-assist: yellow line = current net line, grey ticks = allowed drift window; line the far net pole up with the yellow line), **15 s** after each confirmed point/cobra (with the 'T-Pose!' label), **30 s** after a short button press, and live while the button is held (shutdown countdown).
* **`[STATUS]` journal line every 60 s:** loop time / fps, thread count, net center, CPU temperature and clock. Check with `journalctl -u scoreboard -f`.
* **Interval timing uses `time.monotonic()`**: the Pi has no RTC, so its wall clock jumps by hours when Wi-Fi/NTP syncs after a battery swap (seen Oct 1: 12:06 → 14:43).\n* **Power button and heartbeat run on their own threads**, so the button works (and the heartbeat stops) even while the camera is down.\n* **Deploys** go through a backup → compile check on the Pi → install → 45 s health check → automatic rollback to `~/Documents/backups/<timestamp>/` if the service fails.

### Net Pole Detection Status
Not implemented yet. With the scoreboard on the court side of the near pole, only the far pole (~10 m away, a few pixels wide) is in view, alongside tree trunks, light poles and fence posts; none of the existing field frames were taken from that position, so a detector cannot be validated yet. Plan: collect FieldCaptures from the real mounting position first, then build and test the detector (Section 20) against them. Until then, aim the camera with the OLED aim-assist; the auto-calibrator stays clamped to ±7% (≈7° on a ~100° lens).

---

## 24. Pose Event Logging (T-pose tuning data)

`PoseEventLogger` records the data needed to tune the T-pose `if` statement:
* **`FieldCaptures/PoseEvents/<date>_<time>_<side>_<TPOSE|COBRA>/`** for every confirmed point or cobra: the **12 frames before** the trigger, the trigger frame, and **6 after** (~6 s total at ~2.9 fps), as annotated JPEGs (`00_pre-11.jpg` … `11_TRIGGER.jpg` … `17_post+6.jpg`) plus `frames.json`. Each person is drawn green (T-pose), orange (arms spread but rejected) or grey, labelled with the checks they failed (`low_conf`, `shoulder_w`, `tilt`, `height_align`, `arm_spine_angle`, `joint_order`, `wingspan`, `elbow_straight`) and the measured values (confidence, shoulder width, tilt, height offset / tolerance, arm-to-spine angles, wingspan ratio / required, elbow angles). The header shows the 2-of-3 window state per side.
* **`FieldCaptures/PoseEvents/tpose_candidates.jsonl`**: one JSON line for every person in every frame whose arms are spread (joint order passes), including near misses that never scored. Rotated at 50 MB.
* The newest 300 event folders are kept.

Field observations (Oct 1 indoor test): the flicker of wrist confidence, not the geometry, caused most of the slow confirmations; rejected frames were otherwise arms moving up/down (`arm_spine_angle` 150–175°, `height_align`).

### Close-range T-poses (Oct 1 indoor test, 4 PoseEvents analysed)
* Players a few metres from the ground-level camera with the whole body in frame are confirmed within 2-3 frames.
* Players **within ~2 m** of the camera have their head and shoulders **above the top of the frame** (camera on the ground looking level; the bottom ~25% of the image is floor/sand). MoveNet then only guesses the upper body: shoulder confidence 0.16-0.34, often with left/right swapped; elbows/wrists 0.03-0.3. No keypoint rule can recover a T-pose from that without accepting random arm movements.
* A "hand off the frame edge" rule (substitute the straight-arm wrist position when it falls outside the image) was implemented and evaluated: **0 extra detections** on the indoor sessions and the 392 game frames (MoveNet pins an off-frame wrist to the edge with medium confidence rather than dropping it), so it was removed. Removing the 2% top crop was also tested and was slightly worse (4 vs 5 detections), so `CROP_TOP_FRACTION` stays 0.02.
* **Fix is physical:** tilt the camera up ~10° (or raise it on the scoreboard). The floor band at the bottom is wasted pixels; ~10° of tilt moves a 2 m-away player's shoulders ~100 px down into the frame while far players' feet stay well inside.

### Left-side / close-range delay fixes (Oct 1, 14 PoseEvents analysed)
Replaying the saved keypoints of all 14 events showed three causes of slow confirmation, all now handled in `check_t_pose`:
1. **Keystone lean.** The ground-level, slightly upward-looking wide-angle camera makes upright people near the edges lean outward: measured **lean ≈ -28°·(x-0.5) + 2.4°** (~+10° at the left edge, ~-10° at the right). Players at x≈0.17 failed the 12° `tilt` cap for 1.5 s while holding a clean T-pose. `KeystoneEstimator` subtracts the expected lean (re-fitted every 60 s from upright people in view, clamped to -45..0°/x and ±6°, shown in the `[STATUS]` line). The correction is only applied when it *reduces* the lean, so a wrong estimate can never make the check stricter.
2. **Mirrored left/right labels.** With the head cut off, MoveNet guesses the player faces away and swaps left/right for the whole body, failing `joint_order`. A T-pose (and cobra) is symmetric, so the labels are swapped back.
3. **Lost wrists.** One unusable wrist (low confidence or not beyond its elbow) is projected as a straight forearm (elbow + upper arm) when the other arm is complete. For **close-range** players (shoulders ≥ 80 px wide *and* within the top 15% of the frame), both wrists may be projected; elbows must still be confident, outside the shoulders, horizontal and perpendicular to the spine.
Results: event replay 74 T-pose frames vs 51 (none lost); left-side confirmations 1-2.6 s sooner. False-positive check (old vs new logic): 392 game frames + all indoor periodic frames, 0 frames lost and 6 new frames, all genuine T-poses (incl. one game T-pose the old logic missed). Cobra detection unchanged. Event images now mark `[L/R swapped]` and `[wrist est: ...]`.

A player whose whole arm is past the left/right frame edge is still rejected (a one-arm rule would score anyone pointing at the edge).

**Camera aim (measured):** at 2-3 m the user's shoulders were at y≈50-90 px and feet at ≈470-480 px of the 648 px crop, leaving ~26% floor at the bottom. **Tilt the camera up ~10°** (~100 px): heads/shoulders come into frame from ~2 m while feet stay inside. Use the 5-minute OLED view after boot to check. The keystone estimator adapts to the new angle automatically.

**USB camera at boot (16:05 power-cycle):** enumerated once cleanly, no disconnects (previous boots showed 1-3).

### 2-2.5 s recognition delay (Oct 1, 17:03 events)
After the keystone/swap/wrist fixes the remaining blocker was `height_align`: it compared elbow/wrist heights with shoulder height in **image** coordinates, so when the whole body appears tilted 10-14° (keystone at the frame edges) the wrists of a perfect T sit 0.4-0.5 shoulder widths above/below shoulder height (tolerance 0.35) and 9-10 consecutive good frames (~3 s) were rejected. Heights are now measured along the player's own hip->shoulder axis, using whichever of body-axis and image-vertical is better (so never stricter than before; the hip axis is unreliable for some close-range frames). Replay of all 22 events: **151 T-pose frames vs 80, 0 lost**; most 17:03 events would have confirmed 6-11 frames (2-3 s) earlier. False-positive check: 0 frames lost and 22 new frames, all genuine T-poses. Test-video recall 44 -> 50 frames; cobra unchanged.

Remaining fixed latency once the pose is held: 2 of 3 frames at ~0.3 s/frame (~0.3-0.6 s), plus ~170 ms of leading silence in `PtHm.wav`/`PtAwy.wav` on the Arduino SD card.

### Boot timeline (17:03 boot, seconds since kernel start; add ~3-5 s of Pi firmware before 0)
camera on USB 1.6 s -> `scoreboard.service` starts 5.8 s -> Python imports done 12.0 s (6.2 s, mostly cold SD-card reads of OpenCV/NumPy/TFLite; ~1.2 s when cached) -> model loaded + camera open 13.8 s -> first frame ~14 s (a 1 s camera warm-up sleep was removed).

### Camera USB drop-outs
The camera (Sonix 0c45:6366) has repeatedly disconnected from USB: 3 times during the 14:43 boot and once at 15:08:12 during a test (~10 s after a point), with no Pi under-voltage (`throttled=0x0`). Software now recovers automatically, but check the camera cable/connector and whether its USB cable runs alongside the LED strip power wiring.

---

## 25. OS Package Updates (Oct 1 2026)

* Raspbian **Buster** (32-bit, EOL) via `legacy.raspbian.org` + `archive.raspberrypi.org`. **318 packages upgraded** (Debian security/point releases incl. OpenSSH deb10u4, OpenSSL 1.1.1n, libc, systemd/udev, Python 3.7 patch release, Syncthing 1.19 -> 1.30), existing config files kept (`--force-confold`). Ran detached via `systemd-run` so an SSH drop could not interrupt dpkg. Log: `~/Documents/backups/apt-upgrade.log`; `/etc` + package lists backed up to `~/Documents/backups/pre-apt-<timestamp>/`.
* **Held on purpose** (`apt-mark showhold`): `raspberrypi-kernel`, `raspberrypi-bootloader`, `rpi-eeprom`, `libraspberrypi*`, `linux-libc-dev` (kernel 5.10 -> 6.1 + boot firmware: highest risk of an unbootable remote Pi), `firmware-brcm80211` (Wi-Fi firmware), and all `vlc`/`libvlc` packages (the Pi Foundation and Raspbian repos carry mismatched VLC builds that cannot be upgraded together; VLC is unused). Unhold with `sudo apt-mark unhold <pkg>` only with physical access available.
* Verified after reboot: `dpkg --audit` clean, no failed units, kernel/boot files unchanged, scoreboard 2.8 fps with 0 restarts, tflite/OpenCV/NumPy/Blinka imports OK.
* **Syncthing fix:** its GUI was bound to a stale LAN IP; Syncthing 1.30 exits when the GUI cannot bind, so it crash-looped after the upgrade. GUI address changed to `0.0.0.0:8384` (password-protected; backup `~/Documents/backups/syncthing-config.xml.bak`).

---

## 26. Long-Run Robustness Audit (Oct 1 2026)

Goal: multi-hour sessions without crashes, runaway storage or memory growth.

* **Memory:** scoreboard RSS on the Pi 203.2 MB at 10 min and 203.8 MB at 20 min (flat), constant thread count. Every buffer is bounded: pose-event history (12 frames), keystone samples (400), calibrator window (cleared every 30 s), save queue **40 items** (was 100; ~2.7 MB per queued frame).
* **Storage:** periodic capture ~530 MB/hour (0.75 s interval, ~110 KB/frame), so a 2-hour session uses ~1 GB; the 5 GB cap is reached after ~9.5 h, then the oldest periodic frames are deleted (250 per check, every 150 saves). Also capped: PoseEvents (300 newest folders), **ConfirmedPoses (2000 newest images, new)**, `tpose_candidates.jsonl` (rotated at 50 MB). Writing stops if SD free space < 2 GB. Directory scan at 12.5k files takes 0.3 s on the writer thread (~2-3 s at the 5 GB cap).
* **Accelerated soak test** (desktop, real main loop on a video at ~24 fps, ~11,500 frames, i.e. about an hour of Pi frames, with all caps shrunk): disk usage, event folders, confirmed images and candidate log all stayed bounded and rotated; thread count constant.
* **Camera reader thread** now catches any exception, releases the capture and re-opens after 2 s (previously one exception would leave the scoreboard blind until reboot). Tested by injecting a failure: frames resumed after 4.4 s.
* **MainLoopWatchdog (new):** if the main loop stops iterating for 60 s (`MAIN_LOOP_STALL_SECONDS`), the process exits and systemd restarts it (`Restart=always`). A disconnected camera does not trigger it (the loop keeps iterating while waiting). Tested: a frozen loop was force-exited (code 1).
* **Background people:** MoveNet returns at most 6 people per half; each is checked independently (cheap). Background crowds can only use detection slots; nearer people (players) score higher and are kept.
* **T-pose minimum size:** `MIN_TPOSE_SHOULDER_PX = 22`. Measured scale: shoulder width ≈ 270 px / distance (m) (~100-120 px at ~2.5 m), so 22 px ≈ 12 m: the far sideline (~9-10 m from the camera, ~28 px) counts; people more than ~2-3 m beyond the court are ignored. To verify on site: T-pose on the far sideline and read `shoulder_w` in that event's `frames.json`.
* **USB camera:** further drop-outs at 17:17:36 / 17:17:58 were `error -71` protocol errors followed by a hub port power-cycle while the camera was being moved; no under-voltage. Recovered automatically each time. Secure the camera's USB cable.

## 27. Sound Files (`Arduino_Scoreboard_Fixed/clean_wavs.py` -> `SD_card_cleaned/`)

The WAV gaps were already digital silence; the audible hiss came from the voice clips being recorded at only 26-47% of full scale, so the fixed 8-bit quantization hiss and the Arduino's PWM/amplifier hiss were loud relative to the speech. `clean_wavs.py` (originals untouched): gentle spectral gate at the 8-bit noise floor, near-silence gated to exact silence, leading silence trimmed to ~5 ms (point sounds started 164-173 ms late) and trailing to 60 ms (music/boot keep their tails), every clip normalized to the same peak (120/127). Voice clips are +6 to +11 dB louder relative to the hiss; correlation with the originals 0.999 (only ~1 LSB of hiss removed). Same 8.3 names and TMRpcm format (16 kHz, 8-bit unsigned mono, 44-byte header): copy `SD_card_cleaned/*.wav` onto the Arduino's SD card. If they are too loud, lower `tmrpcm.setVolume(5)` in the sketch.

---

## 28. Power-Cut Safety (switch-off / flat battery without shutdown)

* **Atomic capture writes:** every JPEG and `frames.json` is written to `<name>.tmp`, flushed to the card (`fsync`), then renamed into place, so a power cut leaves either the complete file or nothing. Before this, power cuts had left 19 zero-byte JPEGs; on startup the capture thread now deletes `*.tmp` leftovers and 0-byte images (it removed those 19 on first run). `tpose_candidates.jsonl` is append-only, so at worst its last line is cut off.
* **Session counter in file names** (`S00002_...`, `frame_S00002_...`, stored in `FieldCaptures/session_counter.txt`, recovered from existing names if that file is damaged). The Pi has no clock battery: after an unclean shutdown it boots with the time of its last hourly save, and offline at the courts it stays wrong, so timestamps can go backwards. All "delete oldest" rotation now sorts by name (session first), never by file time.
* **No Python bytecode writes** (`PYTHONDONTWRITEBYTECODE=1` in the service drop-in; `~/Documents/__pycache__` removed): a `.pyc` truncated by a power cut could otherwise make the import fail and the service restart-loop.
* **Filesystem:** root ext4 (journaled, `noatime`) is repaired automatically at boot (`fsck.repair=yes`, so it never stops at a prompt). A **full check now runs every 25 boots** (`tune2fs -c 25`, about +20 s on those boots); the first ran Oct 1 17:51 after 160 unchecked mounts: both partitions clean, nothing to repair. `/boot` (FAT) is only written by firmware updates, which are held.
* **Deploys** replace files with an atomic `mv` and `sync` afterwards.
* **Arduino:** only reads its SD card (WAV files), so power cuts cannot corrupt it.
* **Remaining risk / options (not done remotely):** the SD card's own controller can be damaged by a power cut during heavy writing; periodic capture writes ~530 MB/hour. Options: lower `SAVE_INTERVAL_SECONDS` (pose events already capture every point), use a high-endurance SD card, or for maximum protection a read-only root (overlay FS) with captures on a USB stick. Set those up only with physical access available.

---

## 29. Capture Rate and Pre-Trigger Bursts (Oct 1 2026)

* `SAVE_INTERVAL_SECONDS = 3.0` (was 0.75): periodic background frames drop from ~530 MB/hour to ~130 MB/hour, cutting SD writes ~4x (less exposure to power-cut damage; the 5 GB cap now lasts ~38 h of running).
* **Pose bursts:** `PoseEventLogger` keeps the last **20 frames + the current one in RAM only** (~55 MB) and writes nothing until a T-pose or cobra is confirmed; then it saves those 20 frames before, the trigger frame and 6 after (27 annotated JPEGs, ~3 MB per point, plus `frames.json`) to `FieldCaptures/PoseEvents/`. Folders are named with the session prefix (`S00003_...`).
* `POSE_EVENT_LOGGING = True` switches the bursts and `tpose_candidates.jsonl` on/off; set it to `False` once T-pose tuning is finished.
* Sections 4 and 19 (0.75 s interval, storage math) are superseded by this section.

---

## 30. Phone Score Display over Bluetooth LE (Oct 1 2026, built, not yet deployed)

**Goal:** live score on the phone (Galaxy S24, Chrome) sitting on top of the scoreboard, with no Wi-Fi. Phone control (+1/−1) comes later, and a native Android app maybe after that. Hard rule: **the Arduino keeps working 100% without the Pi.**

**Decisions (and why):**
* **Bluetooth LE + a Web Bluetooth page** beat a phone hotspot (a tap every game, battery, Android randomizes the hotspot subnet) and a Pi Wi-Fi access point (riskiest Wi-Fi change on a hard-to-reach Pi). An ESP32 add-on was ruled out.
* **The Arduino is the source of truth** and only *broadcasts*: one checksummed line per change (at most every 100ms) and at least once a second on Serial1. It writes only when the whole line fits in the TX buffer, so a missing Pi changes nothing.
* **Pi UART2 (GPIO 0/1)** carries the Arduino link, so Bluetooth can have the main PL011 back. `miniuart-bt` would also have needed a `cmdline.txt` edit and a locked core clock.
* **Bluetooth starts 20s after boot** (`scoreboard-bt.timer`), so the old 8s `hciuart` stall can't come back.
* **Page:** bold solid seven-segment digits (the LED-dot look was hard to read in sun). **Day** theme (white, team color darkened to ≥4.5:1 contrast) is the default for noon sun, and **Night** (black, brightened colors, glow) is for stadium lights. There's an optional colored-background style. Mirrored by default (AWAY left, HOME right) for a phone facing the scorekeeper behind the board, with a flip setting.

**Wiring (pink on the wiring diagram):**

| Wire | From | Via | To |
|---|---|---|---|
| Score state (Arduino → Pi) | Mega **pin 18 (TX1)**, communication header | **10k** in series, then **20k** from the Pi side to GND (5V → 3.3V) | Pi **pin 28** (GPIO 1, RXD2), header row 14 |
| Commands (Pi → Arduino, future phone control) | Pi **pin 27** (GPIO 0, TXD2), header row 14 | **1k** in series | Mega **pin 19 (RX1)** |
| Ground | existing Pi pin 39 ↔ Mega GND | | |

**Boot config:** in `/boot/config.txt`, replace `dtoverlay=disable-bt` with `dtoverlay=uart2`. Nothing else changes (`cmdline.txt` stays as is). The link then appears as `/dev/ttyAMA1` (38400 8N1).

**Line format (Arduino → Pi):** `$S,<home>,<away>,<sportMode>,<scoreTo>,<piOn>,<homeColor>,<awayColor>,<d0>,<d1>,<d2>,<d3>,<event>,<eventSeq>*<XOR>`
* Colors: FastLED hue 0–255, 256 white, 257 rainbow (slider ends, now `HUE_WHITE_BELOW` / `HUE_RAINBOW_ABOVE` in the sketch).
* `d0`–`d3`: the glyphs `UpdateDisplay()` actually drew.
* Events: `HU HD AU AD` buttons, `HP AP` T-pose, `HC AC` cobra, `RS`, `HW AW` win, `MD`, `GT`, `SM`.

**BLE:** name `Scoreboard`, service `b3710001-1a78-4239-800f-cf4fa9544bbe`, state characteristic `b3710002-…` (read + notify, 17 bytes). It notifies on change plus a 2s keep-alive.

**Built and verified on the bench:**
* Firmware compiles for the Mega 2560: 35,106 bytes flash, 4,208 bytes RAM (+330), 3,984 bytes free.
* `pi/scoreboard_link.py` (BlueZ 5.50 over D-Bus, no pip installs) compiles and parses on the Pi's Python 3.7.3. Its imports (`dbus`, `gi`, `serial`) are all present on the Pi.
* Wire-contract tests (`tests/`) build lines from the sketch's own `snprintf` format, then check the Pi packer and the page decoder, the FastLED color port, and the digit table. They all pass and run in CI before each Pages deploy.
* The page (`web/`) was previewed in demo mode: both themes, both color styles, both layouts, and portrait (teams stacked).

**(Done, see section 32.) Was not yet done at the time, needed physical access:** flash the Mega, add the two wires and the divider, make the `config.txt` change, install the services, test with nRF Connect, then merge `phone-display` → `main` to publish the page on GitHub Pages. Step-by-step checklist with rollback: `docs/phone-display.md` in the repo. Full from-scratch Pi setup (including how everything starts on boot): `docs/pi-setup-from-scratch.md`.

**Found while doing this:** the old wiring diagram's Pi header drawing was missing a row (19 rows instead of 20), so the OLED pin labels sat one row high. It was redrawn to scale with every pin numbered, plus the Mega's communication header (pins 14–21).

**Repo:** github.com/jakabo27/Gesture-Controlled-Volleyball-Scoreboard. `main` = known-good state (tag `v1.0-pre-ble`), branch `phone-display` = this work.

---

## 31. Button Chords, Non-Blocking Celebration, Phone Settings, Loudness (Oct 1 2026, built, not yet flashed)

All in the repo's `phone-display` branch. The firmware compiles with no warnings: 35,648 bytes flash, 4,268 bytes RAM, 3,924 bytes free.

**Button chords, rewritten.** Why they were unreliable:
* The first button of a chord scored on its own.
* Recognition was one fixed `delay(400)`, so a slow third or fourth finger turned a 4-chord into a 2-chord.
* After a chord, the code waited for release and then fell through the 3- and 2-button states, so releasing a 4-chord could toggle sound mode or the game-to score, or add points.
* A sport change didn't re-arm `gameWonFirstTime`, so the next game never celebrated.

Now:
* A single press acts instantly.
* If more buttons join within 1.5s, that press is undone (score and win state restored).
* The chord fires **while held**: at once with all 4, or 0.35s after the last button joins for 2 or 3 (`CHORD_SETTLE_MS`), and it announces then.
* All score buttons are then ignored until every one is released.
* Shared functions `setSportMode()`, `setScoreTo()` and `toggleSoundMode()` serve both the chords and the phone. A sport change re-arms the celebration.

**Celebration song, now non-blocking.**
* The old code blocked twice: it waited for the point sound to finish, then for the whole song (Champ.wav ~15s, allWin.wav ~12s). Without an SD card, the buzzer melodies were `delay()` loops.
* Now the WAV is queued and starts when the point sound ends (`serviceAudio()`), and the melodies are a note-by-note state machine.
* Any score button, Reset or cobra calls `stopCelebration()` first, so fixing an accidental winning point is one press on −.
* A Pi T-pose point doesn't cut the song off (it skips its own sound while the song plays).
* The `justPlayedWinningTune` heartbeat workaround was removed, because nothing blocks the loop any more. The only delays left are the boot sound and a 0.3s beep sweep.

**Phone settings.** The Settings dialog on the page now starts with Sport (volleyball / tennis, with a confirmation because it resets the score) and Game to (15 / 21 / 25).
* Path: page → BLE command characteristic `b3710003-…` → the Pi forwards only whitelisted `MODE,0|1` / `TO,15|21|25` as `$C,<cmd>*<XOR>` → Arduino `serviceSerialCommands()` (non-blocking, checksum-checked).
* The new values come back in the state line, so the buttons always show what the scoreboard really has, including chord changes.
* `SCOREBOARD_BLE_SECURE=1` makes writes require pairing. Turn it on before adding score control.
* Tests cover the command whitelist on the Pi, the page and the sketch.

**WAV files.** Yes, they were improved earlier (Section 27, `SD_card_cleaned/`), but they still have to be **copied onto the SD card**. New: `python clean_wavs.py --loud` writes `SD_card_loud/`. It uses look-ahead compression (sliding-max envelope ±3ms, 4:1 above −16dB of the peak, 60ms release) and then the same 120/127 peak.
* Loudness vs the plain cleaned set: voice announcements **+1.6 to +5.9 dB**, music +1.4 to +3.8, short effects +0.2 to +2.5.
* All 30 files verified: 16kHz, 8-bit mono, 44-byte header, peak ≤ 120.
* (A first version without look-ahead made the short effects *quieter*, because the attack let transients through.)

**Why the speaker was quiet (firmware side):**
* TMRpcm with `quality(1)` at 16kHz has a 500-step PWM range, and `setVolume(5)` doubles each 8-bit sample to 0–510. A full-scale clip already fills it, and `setVolume(6)` would clip. So the firmware was never the limit.
* The **clips** were: the originals peak at only 26–47% of full scale.
* Unused bonus: TMRpcm drives an inverted copy on **pin 2** (OC3B). With a differential-input amp, wiring IN+ to pin 5 and IN− to pin 2 (`BRIDGED_AUDIO 1`) gives +6 dB.
* Worth checking on the hardware:
  * the amp's gain pot and supply voltage (12V vs 5V),
  * an RC low-pass (~1k + 10nF) before the amp input, so the 32kHz carrier doesn't eat amp headroom.

**Addendum (beeps):** the built-in beeps were also quiet, for two reasons, both fixed in the sketch (`beep()` helper, `BEEP_PITCH 6`):
* TMRpcm leaves Timer3's PWM output connected to pin 5 after a WAV ends, so `tone()` couldn't drive the pin.
* Most beeps were 50–100 Hz.

**First build dates (for finding amplifier photos):**
* CAD: September 18–21, 2021
* Pose test videos: December 22–25, 2021
* Assembly photos: January 1–4, 2022
* Internal wiring photos: February 27, 2022
* Finished photos and videos: May 15, 2022

The amp isn't identifiable in the saved photos.

**Amplifier identified:** a PAM8403 module (5V, 2 × 3W with volume pot, Amazon, bought Dec 27, 2021). It's the loudness ceiling.
* With 3W into a 4" car coax speaker, a 12–20V class-D board (TPA3110 / TPA3116D2) powered straight from the Ryobi battery through a fuse would be about +7 to +10 dB louder.
* Its inputs are single-ended (G = power ground), so `BRIDGED_AUDIO` stays 0.
* The beeps were kept at their original low tones (`BEEP_PITCH 1`) at the user's request. The pin-release fix stays.

**Amp upgrade shortlist (small, 12V, volume knob):** a PAM8610 board with an on-board volume pot.
* 2 × 15W into 4Ω at 12V. The board is about 28 × 22 mm, about 45 × 48 × 18 mm with the pot.
* It runs on 7–15V only, so it can't take the Ryobi's 18–20.5V directly: it needs a small buck converter set to 12V (2–3A) from the fused battery line.
* Expected about +5 to +7 dB over the PAM8403's ~3W.
* Alternative without a buck: an XH-A232 (TPA3110, 8–26V, straight from the battery), which has no knob, plus a panel-mount 10k pot wired as a divider on its input.


---

## 32. Phone display: deployed, field-tested and hardened (Oct 4 2026)

The software from sections 30-31 went onto the real scoreboard in one session. Full write-up: [`docs/phone-display.md`](phone-display.md). What changed from the plan:

* **Wiring moved to Mega Serial3** (TX3 pin 14, RX3 pin 15). Pins 18/19 were already going to an unused level shifter. The divider is **5.1k + 10k** (3.31 V), because there was no 20k in the parts bin.
* **Two bugs found only on the real Pi.** The GATT characteristics' `Service` property must be a D-Bus *object path*, not a string (BlueZ 5.50: "Failed to obtain service path"), and the Bluetooth radio came up soft-blocked after the overlay change (fixed with `rfkill unblock` in the start unit).
* **Phone control added:** `SCORE`, `SOUND`, `TPOSE` commands. The score buttons share their code with the physical ones. `TPOSE` is handled on the Pi through a flag file in `/dev/shm` that the vision engine checks before sending a pulse, so detection keeps running and logging while scoring is off, and every boot starts with it on.
* **Red/green swap:** the WS2812B strip is GRB but the sketch declares NEOPIXEL (RGB), so the LEDs show red and green swapped; the page copies what the LEDs show.
* **Game clock moved to the scoreboard** after a phone showed 4 h 30 min following a phone switch (it had kept its own clock). The state line grew to 16 fields and the BLE packet to 19 bytes.
* **Sound modes** (effects / "Point home/away" voice / tones) cycle with the 3-button chord or from the phone.
* **Sound glitch fixed:** refreshing the LED strip (~8 ms with interrupts off) at the moment "Raspberry Pi connected" started made the first word stutter, because the WAV player runs from interrupts. The heartbeat-dot refresh now waits until no clip is playing.
* **Bluetooth hardening.** Connections are manual and the Pi never pairs; it forgets stale bonds at startup (a stale bond made an iPhone show endless pairing prompts after "Forget this device"). Phones must send a hello within 8 s or are dropped, and idle ones after 75 s.
* **BlueZ 5.50 crashed** (SEGV/ABRT) when an iPhone connected. `bluetoothd` now restarts itself, and **BlueZ 5.79 was built from source** into `/usr/local` (about 8 minutes; only `-dev` packages added, no Wi-Fi, kernel or firmware changes) and selected with a systemd drop-in that can be deleted to roll back. My first build failed to link because I had disabled the audio profiles that other BlueZ code still references.
* **iPhone:** Safari has no Web Bluetooth; the Bluefy app works (notifications are unreliable there, so the page polls four times a second when they go quiet). Android with Chrome, installed to the home screen, is solid, including with Wi-Fi off.
* **Debugging notes.** A debug print gated on "at least 90 bytes free" in a 64-byte buffer never fired; a stats line needed no gate. A command lost once during a test turned out not to repeat across 12 more.


---

## 33. Pi -> Arduino over the serial link (Oct 5 2026, flashed and bench-tested)

Plan and as-built details: [`docs/plan-serial-points.md`](plan-serial-points.md). Branch `serial-points`.

* **Why:** bench tests on Oct 5 showed the GPIO wires cause most Pi-side trouble. The Pi pulls GPIO 0-8 high for ~17 s while it boots or shuts down, which scored phantom points. The pairs are crossed relative to the old notes (GPIO 5 -> 45, GPIO 6 -> 47, GPIO 19 -> 43), GPIO 21 never reaches pin 42, and a 50 ms pulse can be missed when the Mega's loop stalls 55-81 ms as a clip starts.
* **What:**
  * The vision engine's serial hello (`$C,PI,2`, once a second while frames flow) is now the only sign of life. It drives "Pi connected" / "disconnected" and the heartbeat pixel.
  * Gestures are `$C,PT,<L|R><P|C>,<id>` (camera half, T-pose point or cobra), sent 3 times 150 ms apart, at least 40 ms between any two lines. The Mega remembers the last 8 ids.
  * Camera-left = away, camera-right = home (matches the wiring the scoreboard has been scoring with).
  * The 3 s cooldown is per team.
  * The phone's score taps got ids and repeats too.
  * A version-1 hello (today's engine) still uses the wires, so the firmware can be flashed first.
* **Code:**
  * New `pi/arduino_protocol.py` (message builders + `ArduinoLink`, testable without a Pi).
  * The engine lost `pulse_pin()` / `HeartbeatThread` / `ArduinoHello`.
  * The sketch lost ~80 lines of heartbeat-period timing.
  * The buttons' code is unchanged.
  * CI tests cover the message formats, the sketch's parser, the writer timing (fake clock) and the phone command copies.
* **Docs:** README wiring table and "how it works", the wiring diagram (legacy wires, measured pairs), the architecture diagram (serial link, phone display no longer "planned"), and the Arduino and Pi READMEs.


---

## 34. T-pose tuning after the Oct 5 indoor session (Oct 5 2026)

An indoor session produced 339 periodic frames and 7 event bursts (`PoseEvents`). Replaying them offline with the engine's own functions found:

* **The cobra -1 was lost on a wire, not missed by the camera.** Both camera-right cobras (held 0.8 s) were detected and confirmed. The old engine sends that one on GPIO 21, the wire that carries no signal to the Mega. Serial points (section 33) removes the dependency.
* **A clean T-pose scores 0.3-0.6 s after it first passes** (loop about 3.3 fps, 2 of 3 frames). The "many seconds" came from rejections:
  * **Arms a little below level.** One player held a clear T-pose for 4+ s with the arms about 10-15 degrees below level by eye (the model measures 20-25) and never scored: arm height was 1.5-1.9 times the allowed tolerance.
  * **An arm running off the frame edge** (wrist unreadable, `low_conf`): a T-pose at the right edge took 1.6 s to score.
  * **Noisy wrists** on mid-distance players.
* **Camera calibration** (checkerboard, 20 shots at 1280x720, RMS 0.39-0.40 px): horizontal field of view about **93 degrees**, vertical about 50, focal length about 835 px, optical centre (663, 327). 1080p shows exactly the same view as 720p (more pixels, 22 fps instead of 31), 480p is narrower, so the view is already as wide as this camera gives.
* **Lens correction does not fix the droop.** Undistorting the keypoints with the fisheye model recovered 3 of 49 frames of the five verified poses (21 to 24), changed no scoring time and lost 2 of 35 previously scored poses, so it was not adopted. (My first guess, that the droop was lens distortion, was wrong: in the raw frame the arms really are low.)
* **Relaxed tier (adopted).** Elbows and wrists may hang up to 0.8 shoulder widths below shoulder height (strict 0.35), the arm-to-spine angle may reach 130 degrees (strict 110) and elbows need 125 degrees (strict 135). The limits for arms *above* level are unchanged. A pose that passes only the relaxed limits must be held in 3 of the last 4 frames (about 1 s); strict poses still need 2 of 3. Replayed on the logged frames, 21 of 49 frames of the verified poses passed before and 38 now; the drooping T-pose scores 0.6 s in instead of never; all 35 poses that scored before still pass; and none of the 1,696 sightings in the 339 ordinary court frames newly passed. On the Oct 1 log (1.6 h of active play) the longer hold leaves about 5 short, ambiguous bursts that could have scored, so watch the new `T-window` annotation in the PoseEvents images (`r` = a relaxed-only frame).
* **Tried and rejected:** judging a person on one visible arm when the other leaves the frame. It scored a serving player and a one-arm reach as T-poses.
* **Not covered:** T-poses from far away (none were attempted in this data), and the calibration is thin at the far left and right edges of the image.

`tests/test_tpose_rules.py` pins the rules down with synthetic skeletons (it needs numpy).

---

## 35. Detection strictness on the phone, and no images of an empty room (Oct 5-6 2026)

* **Detection strictness** (Settings > Detection). Four presets of the relaxed T-pose tier from section 34, chosen on the phone and stored on the Pi. All four keep the strict tier exactly as it was (a clean T-pose scores in 2 of 3 frames); they differ in how far arms may hang below level and how long such a pose must be held. Arms above level are never relaxed.

  | | below level (shoulder widths / spine angle) | elbows | hold | what it does |
  |---|---|---|---|---|
  | Stricter | 0.65 / 125 deg | 130 deg | 3 of 4 frames | arms close to level; still scores the drooping pose of section 34 |
  | **Standard** (default) | 0.80 / 130 deg | 125 deg | 3 of 4 | the setting tested on Oct 5 |
  | Looser | 1.10 / 140 deg | 120 deg | 3 of 4 | arms may hang low |
  | Loosest | 1.50 / 150 deg | 110 deg | 4 of 5 | arms out and down count; **can score people who are just standing with their arms away from their sides** |

  The ladder was measured on the Oct 5 frames, not guessed. Every rung kept the same 6 confirmations in the replay and lost none of the 35 poses that had scored; 0.50/120/130 was too strict (it rejected the drooping T-pose), and beyond the Loosest setting the false passes explode (1.5/150/110 let 7 sightings through in ordinary play, 2.0/160/100 let 20). Most of those seven were people standing or walking with their arms out and down, which is why the Loosest rung also wants a longer hold: 4 of 5 frames keeps its Oct 1 false-trigger exposure at the Stricter rung's level (6 bursts in the 1.6 h log, against 11 with the 3 of 4 hold).
  How it flows: the page sends `STRICT,n` over Bluetooth, `scoreboard_link.py` writes `scoreboard_strictness.txt` (atomically, so a power cut cannot leave it half-written) and reports `n` back in bits 6-7 of the state flags, and the engine re-reads the file about once a second (`[STRICTNESS] now Looser (from the phone)` in the journal; the PoseEvents header shows `S<n>`). The setting survives a reboot.
* **No images of an empty room.** The periodic captures (every 3 s) now only happen while at least one person has both shoulders found at least 15 px apart (`people_present()`); while nobody is there the timer stays armed, so the first frame with a person is saved at once. Replayed through the real engine on a video of an empty room, it wrote 0 images where the old code wrote 7 in 30 s; with people in view it saves as before. The `[STATUS]` line shows `periodic_saved` and `empty_frames_skipped`. Event bursts (confirmed points and cobras) were never affected: they only happen when someone is there.
* **A battery death is survivable.** The scoreboard lost power mid-session on Oct 6; the Pi came back by itself (ext4 journal recovery, no errors), every deployed file matched its checksum, and the engine and link service restarted on their own.
