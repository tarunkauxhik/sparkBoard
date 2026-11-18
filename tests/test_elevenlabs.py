"""ElevenLabs provider, tested against a fake HTTP server. No real calls."""
import httpx
import pytest

from adgen.ledger import BudgetExceeded, Ledger
from adgen.providers.elevenlabs import ElevenLabs, ElevenLabsError

SCRIBE_REPLY = {"text": "Waiting for the sting.", "language_code": "eng", "words": [
    {"text": "Waiting", "type": "word", "start": 1.2, "end": 1.6},
    {"text": " ", "type": "spacing", "start": 1.6, "end": 1.7},
    {"text": "sting.", "type": "word", "start": 2.0, "end": 2.4}]}


def make(tmp_path, handler, cap=0.25):
    requests = []

    def route(request: httpx.Request):
        requests.append(request)
        return handler(request)

    ledger = Ledger(tmp_path / "ledger.jsonl", {"elevenlabs": cap})
    voice = ElevenLabs(ledger, "secret-test-key", client=httpx.Client(transport=httpx.MockTransport(route)))
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"RIFF")
    return voice, ledger, requests, audio


def test_transcribe_returns_word_timings_and_records_an_estimate(tmp_path):
    voice, ledger, requests, audio = make(tmp_path, lambda r: httpx.Response(200, json=SCRIBE_REPLY))
    result = voice.transcribe(audio, seconds=6)
    assert result["words"] == [{"word": "Waiting", "start_s": 1.2, "end_s": 1.6},
                               {"word": "sting.", "start_s": 2.0, "end_s": 2.4}]  # spacing items are dropped
    assert ledger.spent("elevenlabs") == pytest.approx(6 * 1 * 0.00012)
    assert b"scribe_v3" in requests[0].content


def test_voice_change_keeps_the_proven_settings_and_never_overwrites(tmp_path):
    voice, ledger, requests, audio = make(tmp_path, lambda r: httpx.Response(200, content=b"MP3"))
    out = tmp_path / "changed.mp3"
    voice.voice_change(audio, out, "voice_1", seconds=6)
    assert out.read_bytes() == b"MP3"
    body = requests[0].content
    assert b"eleven_multilingual_sts_v2" in body and b'"similarity_boost": 0.85' in body
    assert ledger.spent("elevenlabs") == pytest.approx(0.012)  # 6 s at about $0.12 per minute
    with pytest.raises(FileExistsError):
        voice.voice_change(audio, out, "voice_1", seconds=6)


def test_speak_sends_the_model_and_text(tmp_path):
    voice, ledger, requests, _ = make(tmp_path, lambda r: httpx.Response(200, content=b"MP3"))
    voice.speak("[sighs] नमस्ते, link below.", tmp_path / "line.mp3", "voice_1", "eleven_v4")
    assert b'"model_id":"eleven_v4"' in requests[0].content.replace(b" ", b"")
    assert "/text-to-speech/voice_1" in str(requests[0].url)


def test_a_refused_call_is_an_error_and_costs_nothing(tmp_path):
    voice, ledger, _, audio = make(tmp_path, lambda r: httpx.Response(401, text="missing permission"))
    with pytest.raises(ElevenLabsError, match="401"):
        voice.transcribe(audio, seconds=6)
    assert ledger.total() == 0


def test_a_dropped_connection_is_counted(tmp_path):
    def drop(request):
        raise httpx.ReadTimeout("too slow")

    voice, ledger, _, audio = make(tmp_path, drop)
    with pytest.raises(ElevenLabsError, match="no reply"):
        voice.transcribe(audio, seconds=6)
    assert ledger.spent("elevenlabs") > 0


def test_the_cap_is_checked_before_sending(tmp_path):
    voice, ledger, requests, audio = make(tmp_path, lambda r: httpx.Response(200, content=b"MP3"), cap=0.001)
    with pytest.raises(BudgetExceeded):
        voice.voice_change(audio, tmp_path / "out.mp3", "voice_1", seconds=60)
    assert requests == [] and ledger.total() == 0


def test_pick_voice_prefers_the_accent_then_narration(tmp_path):
    voices = {"voices": [
        {"voice_id": "v1", "name": "Priya", "labels": {"accent": "indian", "use_case": "conversational"}},
        {"voice_id": "v2", "name": "Brian", "labels": {"accent": "american", "use_case": "narration"},
         "description": "deep, calm and resonant"},
        {"voice_id": "v3", "name": "Jess", "labels": {"accent": "american", "use_case": "social media"}}]}
    voice, ledger, requests, _ = make(tmp_path, lambda r: httpx.Response(200, json=voices))
    assert voice.pick_voice("neutral General American", "calm, low and smooth") == ("v2", "Brian")
    assert voice.pick_voice("Urban Indian English", "warm") == ("v1", "Priya")
    assert ledger.total() == 0  # reading the voice list is free
