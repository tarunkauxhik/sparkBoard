"""The live provider: real paid calls. It joins the three services behind the same
methods the mock provider has, so the pipeline does not know which one it is using.

- Text (Claude Sonnet) and reviews (Gemini) go to OpenRouter.
- Images (Nano Banana), clips (Veo) go to Kie.
- Transcripts and the voice isolator go to ElevenLabs.
- The face check runs locally (adgen/faces.py).
Every paid call is capped and recorded by the service's own class.
"""
from pathlib import Path

from pydantic import BaseModel

from adgen.faces import FaceMatcher
from adgen.ledger import Ledger
from adgen.providers.elevenlabs import ElevenLabs
from adgen.providers.kie import (
    ASSUMED_IMAGE_USD, ASSUMED_VEO_CLIP_USD, Kie, nano_banana_payload, veo_payload,
)
from adgen.providers.openrouter import GEMINI, OpenRouter
from adgen.qa import LabelArea
from adgen.run import Run


class FinalReview(BaseModel):
    """Gemini's notes on the finished ad. Hints for a person to check, never a pass or fail."""
    notes: str


class LiveProvider:
    placeholder_cast = False

    def __init__(self, ledger: Ledger, run: Run, keys: dict[str, str]):
        self.writer = OpenRouter(ledger, run.dir / "llm", keys["OPENROUTER_API_KEY"])
        self.eyes = OpenRouter(ledger, run.dir / "llm", keys["OPENROUTER_API_KEY"], model=GEMINI)
        self.kie = Kie(ledger, run.dir / "tasks", keys["KIE_API_KEY"])
        self.voice = ElevenLabs(ledger, keys["ELEVENLABS_API_KEY"])
        self.faces = FaceMatcher()
        self.run = run
        self.uploaded: dict[Path, str] = {}  # Kie keeps uploads for 24 hours: one upload per file per run
        self.voices: dict[str, tuple[str, str]] = {}  # narrator name -> (voice id, voice name)

    def chat_json(self, task: str, ctx: dict, feedback: str = "") -> dict:
        return self.writer.chat_json(task, ctx, feedback)

    def _url(self, path: Path) -> str:
        if path not in self.uploaded:
            self.uploaded[path] = self.kie.upload(path)
        return self.uploaded[path]

    def _task_name(self, out: Path) -> str:
        """A name for the task log that is unique in the run, e.g. keyframes_s01_take1."""
        return out.relative_to(self.run.dir).with_suffix("").as_posix().replace("/", "_")

    def image(self, prompt: str, refs: list[Path], out: Path, aspect_ratio: str = "9:16") -> None:
        payload = nano_banana_payload(prompt, [self._url(Path(ref)) for ref in refs], aspect_ratio)
        self.kie.run_task(self._task_name(out), payload, ASSUMED_IMAGE_USD, out)

    def video(self, prompt: str, image: Path, out: Path, model: str, duration_s: int) -> str:
        if model not in ASSUMED_VEO_CLIP_USD:
            raise ValueError(f"{model} is not a live video model (Kling Avatar is a documented fallback only)")
        payload = veo_payload(prompt, self._url(image), model, duration_s)
        return self.kie.run_task(self._task_name(out), payload, ASSUMED_VEO_CLIP_USD[model], out)["task_id"]

    def transcribe(self, path: Path, expected: str, duration_s: float) -> list[dict]:
        return self.voice.transcribe(path, duration_s)["words"]

    def isolate(self, media: Path, out: Path, duration_s: float) -> None:
        self.voice.isolate(media, out, duration_s)

    def narrator_voice(self, member) -> tuple[str, str]:
        """The ElevenLabs voice for an off-screen narrator, chosen once per run."""
        if member.name not in self.voices:
            self.voices[member.name] = self.voice.pick_voice(member.accent, member.voice)
        return self.voices[member.name]

    def speak(self, text: str, out: Path, voice_id: str) -> None:
        self.voice.speak(text, out, voice_id)

    def find_label_area(self, image: Path) -> tuple[float, float, float, float] | None:
        """Ask Gemini where the blank label area on the product is (a box, not a judgement)."""
        question = ("This image shows a product with one blank, plain label area meant for printed text "
                    "(for example a date). Give the tightest box around that blank area, in thousandths of the "
                    "image width (left, right) and height (top, bottom). If there is no blank label area, "
                    "set found to false.")
        return self.eyes.look_at(f"label_{image.stem}", question, LabelArea, images=[image]).box()

    def review(self, small_video: Path, seconds: float) -> str:
        question = ("This is a finished short social video ad made with AI video models. Watch it as a strict "
                    "reviewer and list every concrete problem you see or hear, with its time in seconds: "
                    "objects that appear, vanish or change, warped hands, a face that changes, lip-sync that is "
                    "off, text that is garbled. If you see no problem, say so.")
        return self.eyes.look_at("final_cut", question, FinalReview, video=small_video, video_seconds=seconds).notes
