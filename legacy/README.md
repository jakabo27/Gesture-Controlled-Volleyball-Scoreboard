# Legacy: the original 2022 Pi script

`2022-pi/PoseEstimationJT.py` (with its helper `myImageFunctions.py`) is the first version of the vision side, kept as it ran in 2022 for comparison with [`pi/PoseEstimationJT_Optimized.py`](../pi/PoseEstimationJT_Optimized.py). It also imports `myDisplayFunctions.py`, which is unchanged and lives in [`pi/`](../pi/).

What changed in the 2026 rework, and why:

| 2022 | 2026 |
|---|---|
| Left half, then the right half only if the left had no T-pose | Both halves every frame, overlapping by 12%: up to 12 players |
| Crashed when MoveNet found exactly one person (`np.squeeze` collapsed the output tensor) | Output shape normalized, detections sorted and clamped |
| ~2,600 `math domain error` exceptions in the logs (`acos` of 1.0000000000000002) | Clamped and guarded |
| Angles in normalized coordinates (a 2.37× vertical stretch) | True pixel-space geometry, tolerances scaled to shoulder width |
| Image-vertical arm checks | Body-axis checks, keystone correction, mirrored-label and lost-wrist handling |
| `imutils` VideoStream on `/dev/video0` | Threaded MJPG grabber on the stable `/dev/v4l/by-id` path, with hung-camera and stale-frame detection |
| Desktop autostart entry | systemd service, watchdog, power-cut-safe logging |
