"""Voice pitch, measured locally. Used to warn when one speaker sounds different between clips.

Veo gives each clip its own voice. In the clips that started this project the "wrong" voice
was about 12% lower in pitch than the others, so pitch is a cheap first signal. It is only
a signal: two different voices can share a pitch.
"""
import subprocess
from pathlib import Path

import numpy as np

RATE = 16000
FRAME, HOP = 640, 160      # 40 ms windows, every 10 ms
LOWEST_HZ, HIGHEST_HZ = 75, 400
VOICED = 0.5               # how strongly a window must repeat to count as voiced speech


def median_pitch_hz(media: Path, start_s: float, end_s: float) -> float | None:
    """Median speaking pitch between two times. None if no voiced speech is found."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(start_s), "-to", str(end_s), "-i", str(media),
         "-vn", "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"], capture_output=True, check=True).stdout
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    shortest, longest = RATE // HIGHEST_HZ, RATE // LOWEST_HZ  # the lag range of a human voice
    pitches = []
    for begin in range(0, len(samples) - FRAME, HOP):
        window = samples[begin:begin + FRAME] - samples[begin:begin + FRAME].mean()
        energy = float(window @ window)
        if energy < 1e6:  # silence
            continue
        # How well the window matches itself shifted by each lag; the best lag is one pitch period.
        match = np.correlate(window, window, "full")[FRAME - 1 + shortest: FRAME + longest]
        lag = int(match.argmax())
        if match[lag] / energy >= VOICED:
            pitches.append(RATE / (lag + shortest))
    return float(np.median(pitches)) if pitches else None
