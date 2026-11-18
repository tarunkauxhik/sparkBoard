"""Finding and removing stray clicks between words, on made-up audio. No paid calls."""
import subprocess

import numpy as np

from adgen.clicks import RATE, find_clicks, turn_down
from adgen.schemas import Word

WORDS = [Word(word="hello", start_s=1.0, end_s=1.6), Word(word="there", start_s=1.7, end_s=2.3)]


def write(samples: np.ndarray, path) -> None:
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "s16le", "-ar", str(RATE), "-ac", "1", "-i", "-", str(path)],
                   input=pcm.tobytes(), check=True)


def speech_with(click_at: float | None, tmp_path):
    """3 s of near-silence, a 200 Hz 'voice' over the two words, and an optional 20 ms click."""
    t = np.arange(3 * RATE) / RATE
    audio = np.random.default_rng(1).normal(0, 0.0003, len(t))      # very quiet room
    for word in WORDS:
        inside = (t >= word.start_s) & (t <= word.end_s)
        audio[inside] += 0.3 * np.sin(2 * np.pi * 200 * t[inside])
    if click_at is not None:
        a = int(click_at * RATE)
        audio[a:a + int(0.02 * RATE)] += np.random.default_rng(2).normal(0, 0.05, int(0.02 * RATE))  # bright burst
    path = tmp_path / "clip.wav"
    write(audio, path)
    return path


def test_a_click_before_the_first_word_is_found_and_muted(tmp_path):
    clip = speech_with(0.6, tmp_path)
    clicks = find_clicks(clip, WORDS)
    assert len(clicks) == 1 and clicks[0][0] < 0.6 < clicks[0][1]
    cleaned = tmp_path / "cleaned.wav"
    turn_down(clip, clicks, 0.0, cleaned)
    assert find_clicks(cleaned, WORDS) == []


def test_clean_speech_has_no_clicks(tmp_path):
    assert find_clicks(speech_with(None, tmp_path), WORDS) == []


def test_a_short_pause_inside_the_line_is_left_alone(tmp_path):
    # 1.62 s sits in the 0.1 s pause between the two words: muting there could chop a word
    assert find_clicks(speech_with(1.62, tmp_path), WORDS) == []


def test_a_tap_after_the_line_is_found(tmp_path):
    clicks = find_clicks(speech_with(2.7, tmp_path), WORDS)
    assert len(clicks) == 1 and clicks[0][0] < 2.7 < clicks[0][1]


def test_the_ringing_end_of_a_word_is_not_a_click(tmp_path):
    # seen live: "sting" was marked as ending at 1.52 s but rang on to about 1.78 s
    clip = speech_with(2.42, tmp_path)  # 0.12 s after "there" ends at 2.3 s: still the word's tail
    assert find_clicks(clip, WORDS) == []
