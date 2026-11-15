"""Mock provider for dry runs: canned text, placeholder images and clips. Costs $0.

It still charges the ledger at the estimated prices (marked mock), so a dry run
shows what the real run would cost and exercises the budget cap.
"""
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from adgen.ledger import PRICES, Ledger
from adgen.statics import FONT

COLORS = ["#6b7a8f", "#8f6b6b", "#6b8f76", "#8f866b", "#7a6b8f"]


def _color(seed: str) -> str:
    return COLORS[sum(seed.encode()) % len(COLORS)]


class MockProvider:
    def __init__(self, ledger: Ledger):
        self.ledger = ledger

    # --- text (OpenRouter in the live provider) ---

    def chat_json(self, task: str, ctx: dict) -> dict:
        """Canned answer for one LLM task, built from the brief so it reads sensibly."""
        self.ledger.charge("openrouter", f"sonnet:{task}", PRICES["sonnet_call"], mock=True)
        return getattr(self, f"_{task}")(ctx)

    def review(self, path: Path, rubric: str) -> dict:
        self.ledger.charge("openrouter", f"gemini:{rubric}", PRICES["gemini_review"], mock=True)
        return {"passed": True, "detail": "mock review, nothing was really checked"}

    # --- media (Kie in the live provider) ---

    def image(self, prompt: str, refs: list[str], out: Path) -> None:
        """Placeholder 9:16 image with the file name written on it."""
        self.ledger.charge("kie", f"image:{out.stem}", PRICES["image"], mock=True)
        img = Image.new("RGB", (1080, 1920), _color(out.stem))
        draw = ImageDraw.Draw(img)
        draw.text((60, 900), f"MOCK {out.stem}", fill="white", font=ImageFont.truetype(str(FONT), 64))
        img.save(out)

    def video(self, prompt: str, image: Path, out: Path, model: str, duration_s: int) -> str:
        """Placeholder clip shaped like a Veo take (720x1280, 24 fps, tone as audio)."""
        if out.exists():
            raise FileExistsError(f"refusing to overwrite raw take {out}")
        price = PRICES["kling_avatar_per_s"] * duration_s if model == "kling_avatar" else PRICES[model]
        self.ledger.charge("kie", f"{model}:{out.stem}", price, mock=True)
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y",
             "-f", "lavfi", "-i", f"color=c={_color(out.stem)}:s=720x1280:r=24:d={duration_s}",
             "-f", "lavfi", "-i", f"sine=frequency=220:sample_rate=48000:duration={duration_s}",
             "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)],
            check=True,
        )
        return f"mock-task-{out.stem}"

    # --- audio (ElevenLabs in the live provider) ---

    def voice_change(self, src: Path, out: Path, voice: str, duration_s: int) -> None:
        self.ledger.charge("elevenlabs", f"voice_change:{out.stem}",
                           PRICES["voice_change_per_s"] * duration_s, mock=True)
        shutil.copyfile(src, out)

    def transcribe(self, path: Path, expected: str, duration_s: int) -> list[dict]:
        """Word timings: the expected words spread evenly over the clip."""
        self.ledger.charge("elevenlabs", f"scribe:{path.stem}",
                           PRICES["scribe_per_s"] * duration_s, mock=True)
        words = expected.split()
        step = duration_s / max(len(words), 1)
        return [{"word": w, "start_s": round(i * step, 2), "end_s": round((i + 1) * step, 2)}
                for i, w in enumerate(words)]

    # --- canned LLM answers ---

    def _insights(self, ctx: dict) -> dict:
        brief = ctx["brief"]
        return {
            "pains": [f"{brief['audience']} have tried products like this and felt let down"],
            "desires": ["something simple that fits into the day they already have"],
            "objections": ["will it work for me?", "is it worth the price?"],
            "proof_points": [f"{brief['product']} does one clear job"],
        }

    def _concepts(self, ctx: dict) -> dict:
        product = ctx["brief"]["product"]
        ideas = [
            ("c1", "Honest first week", f"I almost returned this {product}.", 8.5),
            ("c2", "The skeptic friend", "My friend would not stop talking about it.", 7.5),
            ("c3", "Morning routine", "This is the only step I never skip.", 7.0),
            ("c4", "Before the meeting", "Ten minutes before the call, I panicked.", 6.5),
            ("c5", "Unboxing", "Okay, it finally came.", 6.0),
        ]
        return {
            "concepts": [{"id": i, "title": t, "hook": h, "score": s,
                          "insight": ctx["insights"]["pains"][0]} for i, t, h, s in ideas],
            "winner_id": "c1",
            "reason": "strongest hook, and it answers the 'will it work for me?' objection (mock)",
        }

    def _look(self, ctx: dict) -> dict:
        category = ctx["brief"]["category"]
        return {field: {"value": value, "reason": f"from the {category} playbook (mock)"}
                for field, value in ctx["playbook"].items()}

    def _storyboard(self, ctx: dict) -> dict:
        brief = ctx["brief"]
        talk = {"shot_type": "medium close-up", "angle": "eye level, front phone camera",
                "framing": "head and shoulders, slightly off-center", "character": "maya",
                "speaker": "maya", "lighting": "soft window light from the left",
                "location": "bathroom_plate", "camera_move": "handheld, slight sway",
                "duration_s": 6, "route": "veo_talk"}

        def line(text: str) -> dict:
            return {"dialogue_tts": text, "dialogue_caption": text}

        return {
            "title": ctx["concept"]["title"],
            "characters": [{"name": "maya", "description": "woman in her late 20s, shoulder-length dark hair",
                            "outfit": "a plain grey t-shirt", "voice": "mock-voice-1"}],
            "shots": [
                {**talk, "id": "s01", "purpose": "hook", "expression": "a little embarrassed",
                 "action": "holds the bottle up near her face",  "product_visible": True,
                 **line(f"Okay, I almost returned this {brief['product']}. Honestly.")},
                {**talk, "id": "s02", "purpose": "problem", "expression": "tired, half-smile",
                 "action": "touches her cheek, then looks into the lens",
                 **line("I have tried so many things, and nothing really changed.")},
                {"id": "s03", "purpose": "product", "duration_s": 4, "shot_type": "close-up",
                 "angle": "top down", "framing": "bottle resting on the counter, off-center",
                 "action": "a hand sets the bottle down next to a towel",
                 "lighting": "soft window light from the left", "location": "bathroom_plate",
                 "product_visible": True, "camera_move": "static", "route": "veo_broll"},
                {**talk, "id": "s04", "purpose": "payoff", "expression": "relaxed smile",
                 "action": "shrugs and smiles at the lens",
                 **line(f"Two weeks in, I get it now. {brief['brand']}, try it.")},
            ],
        }

    def _edit_list(self, ctx: dict) -> dict:
        return {
            "cuts": [{"shot_id": c["shot_id"], "file": c["file"], "in_s": 0.0, "out_s": c["duration_s"],
                      "reason": "storyboard order, full take (mock)"} for c in ctx["clips"]],
            "end_card": {"line": f"Try {ctx['brief']['brand']}", "duration_s": 2.0},
        }
