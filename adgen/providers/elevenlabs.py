"""ElevenLabs: voice changer, text to speech and transcripts (Scribe).

Endpoints and fields were checked against elevenlabs.io/docs on 16 Nov 2026.
The voice changer settings are the ones that worked in the voice-fix task (15 Nov 2026).

Cost: ElevenLabs does not return the price of a call, and the account is shared, so its
usage counter cannot be split per call. The ledger therefore records an estimate from the
known credit rates below; smoke step E compares the total with the account's usage counter.
"""
import json
import subprocess
import time
from pathlib import Path

import httpx

from adgen.ledger import Ledger

API = "https://api.elevenlabs.io/v1"
USD_PER_CREDIT = 0.00012                   # 4,157 credits were about $0.50 in the voice-fix task
VOICE_CHANGER_CREDITS_PER_S = 1000 / 60    # measured: 3,896 credits for 3.9 minutes
SCRIBE_CREDITS_PER_S = 1                   # measured about 0.45 in the smoke test; kept on the high side
TTS_CREDITS_PER_CHAR = 1
SAFETY = 2                                 # the cap check assumes a call costs twice the estimate
VOICE_CHANGER_MODEL = "eleven_multilingual_sts_v2"
SCRIBE_MODEL = "scribe_v3"
TTS_MODEL = "eleven_v4"  # the default since the smoke test: no word errors, and v3 sounded bad on a library voice
ISOLATOR_CREDITS_PER_S = 1000 / 60         # assumed the same rate as the voice changer
ISOLATOR_MIN_S = 5.0                       # the isolator refuses audio under 4.6 s (measured live)
VOICE_SETTINGS = {"stability": 0.5, "similarity_boost": 0.85, "style": 0.0, "use_speaker_boost": True}
SEED = 42


class ElevenLabsError(RuntimeError):
    pass


class ElevenLabs:
    def __init__(self, ledger: Ledger, api_key: str, client: httpx.Client | None = None):
        self.ledger = ledger
        self.headers = {"xi-api-key": api_key}
        self.client = client or httpx.Client(timeout=180)

    def _paid(self, item: str, credits: float, send) -> httpx.Response:
        """One paid call: cap check first, the estimate recorded after. A failed HTTP status
        is not billed; a dropped connection may be, so it is recorded too."""
        cost = credits * USD_PER_CREDIT
        self.ledger.check("elevenlabs", cost * SAFETY)
        try:
            response = send()
        except httpx.HTTPError as error:
            self.ledger.record("elevenlabs", f"{item} (no reply, estimate)", cost)
            raise ElevenLabsError(f"{item}: no reply ({error!r}); counted as ${cost:.4f}")
        if response.status_code != 200:
            raise ElevenLabsError(f"{item}: HTTP {response.status_code}: {response.text[:300]}")
        self.ledger.record("elevenlabs", item, cost)
        return response

    def credits_used(self, days: int = 30) -> dict[str, int]:
        """Credits the whole account used per product over the last days. A free call."""
        now = int(time.time() * 1000)
        usage = self.client.get(f"{API}/usage/character-stats", headers=self.headers,
                                params={"start_unix": now - days * 86400 * 1000, "end_unix": now,
                                        "breakdown_type": "product_type"}).json()
        return {product: round(sum(values)) for product, values in usage.get("usage", {}).items()}

    def transcribe(self, audio: Path, seconds: float) -> dict:
        """Scribe transcript: {"text", "language_code", "words": [{"word", "start_s", "end_s"}]}."""
        def send():
            with audio.open("rb") as file:
                return self.client.post(f"{API}/speech-to-text", headers=self.headers,
                                        data={"model_id": SCRIBE_MODEL, "timestamps_granularity": "word"},
                                        files={"file": (audio.name, file)})
        reply = self._paid(f"scribe:{audio.stem}", seconds * SCRIBE_CREDITS_PER_S, send).json()
        words = [{"word": w["text"], "start_s": w["start"], "end_s": w["end"]}
                 for w in reply["words"] if w["type"] == "word"]
        return {"text": reply["text"], "language_code": reply["language_code"], "words": words}

    def voice_change(self, audio: Path, out: Path, voice_id: str, seconds: float) -> None:
        """Re-voice the audio in another voice. Timing is kept, so lip-sync holds.

        NOT USED by the pipeline since 17 Nov 2026. In the smoke test the result sounded bad,
        added a loud click and turned "Rohan" into "Roman". Kept for reference only."""
        if out.exists():
            raise FileExistsError(f"refusing to overwrite {out}")

        def send():
            with audio.open("rb") as file:
                return self.client.post(
                    f"{API}/speech-to-speech/{voice_id}", headers=self.headers,
                    params={"output_format": "mp3_44100_128"},
                    data={"model_id": VOICE_CHANGER_MODEL, "seed": str(SEED), "remove_background_noise": "false",
                          "voice_settings": json.dumps(VOICE_SETTINGS)},
                    files={"audio": (audio.name, file)})
        out.write_bytes(self._paid(f"voice_change:{out.stem}", seconds * VOICE_CHANGER_CREDITS_PER_S, send).content)

    def pick_voice(self, accent: str, description: str) -> tuple[str, str]:
        """(voice id, name) of the account voice whose labels best match a persona. A free call.
        Accent counts most, then narration use, then words of the voice description."""
        voices = self.client.get(f"{API}/voices", headers=self.headers).json()["voices"]

        def score(voice: dict) -> int:
            labels = " ".join(str(v) for v in (voice.get("labels") or {}).values()).lower()
            text = f"{labels} {voice.get('description') or ''}".lower()
            accent_hit = any(word in labels for word in accent.lower().replace(",", " ").split() if len(word) > 3)
            words = {w.strip(",.") for w in description.lower().split() if len(w) > 3}
            return 4 * accent_hit + 2 * ("narrat" in text) + sum(word in text for word in words)

        best = max(voices, key=score)
        return best["voice_id"], best.get("name", "")

    def isolate(self, audio: Path, out: Path, seconds: float) -> None:
        """Voice Isolator: keep the voice, remove room sound and background noise.
        The isolator refuses audio under 4.6 s, so shorter audio is padded with silence before
        it is sent, and the cleaned voice is cut back to the original length."""
        if out.exists():
            raise FileExistsError(f"refusing to overwrite {out}")
        padded = out.with_name(f"{out.stem}_padded.wav")
        sent = max(seconds, ISOLATOR_MIN_S)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(audio), "-vn", "-ac", "1",
                        "-af", f"apad=whole_dur={sent}", str(padded)], check=True)

        def send():
            with padded.open("rb") as file:
                return self.client.post(f"{API}/audio-isolation", headers=self.headers,
                                        files={"audio": (padded.name, file)})
        cleaned = out.with_name(f"{out.stem}_cleaned{out.suffix}")
        cleaned.write_bytes(self._paid(f"isolate:{out.stem}", sent * ISOLATOR_CREDITS_PER_S, send).content)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(cleaned), "-t", f"{seconds:.3f}", str(out)],
                       check=True)
        padded.unlink()
        cleaned.unlink()

    def speak(self, text: str, out: Path, voice_id: str, model_id: str = TTS_MODEL) -> None:
        """Text to speech. The text may hold audio tags like [sighs] and mixed-script Hinglish.
        (Its `speed` setting made no difference with eleven_v4 in testing; lines that are too
        long are time-stretched in code instead, see editor.time_stretch.)"""
        if out.exists():
            raise FileExistsError(f"refusing to overwrite {out}")
        body = {"text": text, "model_id": model_id, "seed": SEED}

        def send():
            return self.client.post(f"{API}/text-to-speech/{voice_id}", headers=self.headers,
                                    params={"output_format": "mp3_44100_128"}, json=body)
        out.write_bytes(self._paid(f"tts:{out.stem}", len(text) * TTS_CREDITS_PER_CHAR, send).content)
