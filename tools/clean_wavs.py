"""
Cleans the scoreboard's SD-card sound effects (TMRpcm format: 16 kHz, 8-bit unsigned, mono, 44-byte header).

Why: the voice clips were recorded at only 26-47% of full scale, so the fixed 8-bit quantization hiss and the
Arduino's PWM/amplifier hiss are loud relative to the speech. For every file this script:
  1. reduces low-level hiss with a gentle spectral gate (bins near the 8-bit noise floor are attenuated),
  2. gates near-silent stretches to exact digital silence,
  3. trims dead air: leading silence to 5 ms, trailing silence to 60 ms (music and the boot jingle keep
     their tails),
  4. normalizes the peak to TARGET_PEAK so every clip plays at the same, louder level.
Originals are never modified; cleaned files (same 8.3 names) go to SD_card_cleaned/.

--loud additionally compresses each clip before normalizing (fast envelope, 4:1 above -16 dB of the peak), so
the quiet parts of every word come up while the peaks stay at the same no-clip ceiling. Same peak, roughly
+3 to +5 dB more average level: noticeably louder through the same amplifier. Output: SD_card_loud/.
The Arduino can't go louder digitally: at setVolume(5) a peak of 120 already drives the PWM to ~97%.

Usage:  python clean_wavs.py [--loud] [folder with the original WAVs]   (default: this script's folder)
"""
import glob
import os
import sys
import wave

import numpy as np

LOUD = '--loud' in sys.argv
_args = [a for a in sys.argv[1:] if not a.startswith('--')]
SRC_DIR = os.path.abspath(_args[0]) if _args else os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SRC_DIR, 'SD_card_loud' if LOUD else 'SD_card_cleaned')
TARGET_PEAK = 120.0            # of 127 (about -0.5 dBFS): headroom for TMRpcm's 2x oversampling
KEEP_TAILS = {'Boot.wav', 'Champ.wav', 'allWin.wav'}   # music / jingles: don't trim their endings
FRAME = 512                    # STFT size (32 ms at 16 kHz)
HOP = 128


def read_u8(path):
    with wave.open(path) as w:
        assert w.getsampwidth() == 1 and w.getnchannels() == 1, path
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.uint8).astype(np.float64) - 128.0
    return sr, x


def write_u8(path, sr, x):
    q = np.clip(np.round(x) + 128.0, 0, 255).astype(np.uint8)
    with wave.open(path, 'wb') as w:       # plain PCM: 44-byte header, which TMRpcm expects
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(sr)
        w.writeframes(q.tobytes())


def spectral_gate(x):
    """Attenuates STFT bins that are within a few times the 8-bit quantization noise floor."""
    if len(x) < FRAME:
        return x
    win = np.hanning(FRAME)
    pad = np.concatenate([np.zeros(FRAME), x, np.zeros(FRAME)])
    n_frames = 1 + (len(pad) - FRAME) // HOP
    out = np.zeros(len(pad))
    norm = np.zeros(len(pad))
    # Uniform quantization noise: variance 1/12 per sample (LSB = 1) -> expected |X| per bin
    noise_mag = np.sqrt(np.sum(win ** 2) / 12.0)
    for i in range(n_frames):
        s = i * HOP
        spec = np.fft.rfft(pad[s:s + FRAME] * win)
        mag = np.abs(spec) + 1e-9
        gain = np.clip(1.0 - (2.5 * noise_mag / mag) ** 2, 0.0, 1.0)   # Wiener-style soft mask
        out[s:s + FRAME] += np.fft.irfft(spec * gain) * win
        norm[s:s + FRAME] += win ** 2
    out = out / np.maximum(norm, 1e-9)
    return out[FRAME:FRAME + len(x)]


def gate_and_trim(sr, x, keep_tail):
    win = max(1, int(sr * 0.01))
    rms = np.sqrt(np.convolve(x ** 2, np.ones(win) / win, mode='same'))
    active = rms > max(1.5, 0.03 * np.abs(x).max())
    if not active.any():
        return x
    # Gate: silence quiet stretches (with a 10 ms ramp so the gate itself doesn't click)
    env = np.convolve(active.astype(float), np.ones(win) / win, mode='same')
    x = x * np.clip(env * 1.5, 0.0, 1.0)
    first = max(0, int(np.argmax(active)) - int(sr * 0.005))
    last = len(x) if keep_tail else min(len(x), len(active) - int(np.argmax(active[::-1])) + int(sr * 0.06))
    return x[first:last]


def compress(sr, x, threshold_db=-16.0, ratio=4.0, lookahead_ms=3.0, release_ms=60.0):
    """Look-ahead peak compressor: gain reduction above threshold_db (relative to the clip's peak).
    The envelope is the sliding maximum over +-lookahead_ms (so the gain is already down when a transient
    arrives, and the envelope is never below the signal), released smoothly afterwards."""
    a = np.abs(x)
    peak = max(a.max(), 1e-9)
    thr = peak * 10 ** (threshold_db / 20.0)
    L = max(1, int(sr * lookahead_ms / 1000.0))
    held = np.lib.stride_tricks.sliding_window_view(np.pad(a, (L, L)), 2 * L + 1).max(axis=1)
    a_rel = np.exp(-1.0 / (sr * release_ms / 1000.0))
    env = np.empty_like(held)
    e = 0.0
    for i, v in enumerate(held):
        e = v if v > e else a_rel * e + (1 - a_rel) * v
        env[i] = e
    gain = np.where(env > thr, (env / thr) ** (1.0 / ratio - 1.0), 1.0)
    return x * gain


def active_rms(x):
    """RMS over the whole clip (compression is sample-for-sample, so both versions have the same length)."""
    return np.sqrt(np.mean(x ** 2)) if len(x) else 0.0


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"{'file':11s} {'old peak':>8s} {'new peak':>8s} {'gain dB':>7s} {'old dur':>7s} {'new dur':>7s} {'lead trimmed':>12s}")
    for path in sorted(glob.glob(os.path.join(SRC_DIR, '*.wav'))):
        name = os.path.basename(path)
        sr, x = read_u8(path)
        old_peak = np.abs(x).max()
        y = spectral_gate(x)
        y = gate_and_trim(sr, y, keep_tail=name in KEEP_TAILS)
        plain = y * (TARGET_PEAK / max(np.abs(y).max(), 1e-9))
        if LOUD:
            y = compress(sr, y)
        y = y * (TARGET_PEAK / max(np.abs(y).max(), 1e-9))
        if LOUD:
            print(f"{name:11s} loudness vs plain clean: {20 * np.log10(active_rms(y) / max(active_rms(plain), 1e-9)):+5.1f} dB")
        write_u8(os.path.join(OUT_DIR, name), sr, y)
        _, z = read_u8(os.path.join(OUT_DIR, name))
        lead_old = np.argmax(np.abs(x) > 2) / sr * 1000
        lead_new = np.argmax(np.abs(z) > 2) / sr * 1000
        print(f"{name:11s} {old_peak:8.0f} {np.abs(z).max():8.0f} {20 * np.log10(np.abs(z).max() / old_peak):+7.1f} "
              f"{len(x) / sr:6.2f}s {len(z) / sr:6.2f}s {lead_old:6.0f}->{lead_new:3.0f}ms")


if __name__ == '__main__':
    main()
