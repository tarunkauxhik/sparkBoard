"""Stray clicks and taps in the gaps between words: find them, and mute or duck them.

Veo sometimes adds a lip click before a line or a tap from the room. Under Veo's room tone
they are hard to hear, but once the voice isolator removes the room they stand out alone in
silence (smoke test: a click at 1.2 s, just before the first word). A click is short, bright
(most of its energy above 2 kHz) and much louder than the quiet around it. Words are left
alone: the transcript's word timings mark where speech is.
"""
import subprocess
from pathlib import Path

import numpy as np

from adgen.schemas import Word

RATE = 48000
WINDOW_S = 0.005          # 5 ms analysis windows
BRIGHT_HZ = 2000
MIN_BRIGHT_SHARE = 0.6    # share of a window's energy above 2 kHz
MIN_RISE_DB = 12          # how far above the quiet between words a click must be
MIN_LEVEL_DB = -55        # quieter than this is inaudible under any bed
MAX_CLICK_S = 0.12        # longer bright sounds are not clicks (breaths, hiss)
SPEECH_BEFORE_S, SPEECH_AFTER_S = 0.12, 0.30  # transcripts start words late and end them early
                                              # (an "s" begins before; a word like "sting" rings on after)
MIN_GAP_S = 0.25          # pauses shorter than this inside a line count as speech
PAD_BEFORE_S, PAD_AFTER_S = 0.03, 0.06  # muted around each click: its quiet start and its ring-out
FADE_S = 0.005             # fades in and out of each mute, so the mute itself makes no click


def _samples(media: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(media), "-vn", "-ac", "1", "-ar", str(RATE),
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768


def find_clicks(media: Path, words: list[Word]) -> list[tuple[float, float]]:
    """(start, end) in seconds of every click or tap outside the spoken words."""
    samples = _samples(media)
    size = int(WINDOW_S * RATE)
    windows = samples[: len(samples) // size * size].reshape(-1, size)
    if not len(windows):
        return []
    spectrum = np.abs(np.fft.rfft(windows * np.hanning(size), axis=1)) ** 2
    bright = spectrum[:, np.fft.rfftfreq(size, 1 / RATE) > BRIGHT_HZ].sum(1) / np.maximum(spectrum.sum(1), 1e-12)
    level = 20 * np.log10(np.sqrt((windows ** 2).mean(1)) + 1e-9)
    times = np.arange(len(windows)) * WINDOW_S
    speech = np.zeros(len(windows), dtype=bool)
    for i, word in enumerate(words):
        # A short pause inside the line belongs to the speech: muting there would chop words.
        follows = words[i + 1].start_s if i + 1 < len(words) else None
        end = follows if follows is not None and follows - word.end_s < MIN_GAP_S else word.end_s
        speech |= (times >= word.start_s - SPEECH_BEFORE_S) & (times <= end + SPEECH_AFTER_S)
    gaps = level[~speech]
    if not len(gaps):
        return []
    quiet = float(np.median(gaps))
    hit = ~speech & (bright >= MIN_BRIGHT_SHARE) & (level >= max(quiet + MIN_RISE_DB, MIN_LEVEL_DB))

    clicks, start = [], None
    for i, on in enumerate(np.append(hit, False)):
        if on and start is None:
            start = i
        elif not on and start is not None:
            # allow one quiet window inside a click before calling it ended
            if i + 1 < len(hit) and hit[i + 1]:
                continue
            begin, end = times[start], times[i - 1] + WINDOW_S
            if end - begin <= MAX_CLICK_S:
                clicks.append((round(float(max(0.0, begin - PAD_BEFORE_S)), 3), round(float(end + PAD_AFTER_S), 3)))
            start = None
    merged = []  # padding can make neighbouring clicks overlap: join them
    for begin, end in clicks:
        if merged and begin <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((begin, end))
    return merged


def turn_down(media: Path, clicks: list[tuple[float, float]], level: float, out: Path) -> None:
    """Write the audio of `media` to `out` (a .wav) with every click turned down to `level`
    (0 mutes). Done sample by sample: ffmpeg's timed volume only switches every ~20 ms."""
    samples = _samples(media)
    gain = np.ones(len(samples), dtype=np.float32)
    fade = int(FADE_S * RATE)
    for start, end in clicks:
        a, b = int(start * RATE), min(int(end * RATE), len(samples))
        gain[a:b] = level
        gain[max(0, a - fade):a] = np.linspace(1, level, a - max(0, a - fade))
        gain[b:b + fade] = np.linspace(level, 1, len(gain[b:b + fade]))
    pcm = (np.clip(samples * gain, -1, 1) * 32767).astype(np.int16)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "s16le", "-ar", str(RATE), "-ac", "1", "-i", "-", str(out)],
                   input=pcm.tobytes(), check=True)
