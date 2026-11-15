"""Mock provider for dry runs: canned text, placeholder images and clips. Costs $0.

It still charges the ledger at the estimated prices (marked mock), so a dry run
shows what the real run would cost and exercises the budget cap.
"""
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from adgen.ledger import PRICES, Ledger
from adgen.schemas import EDGE_SILENCE_S
from adgen.statics import FONT

COLORS = ["#6b7a8f", "#8f6b6b", "#6b8f76", "#8f866b", "#7a6b8f"]


def _color(seed: str) -> str:
    return COLORS[sum(seed.encode()) % len(COLORS)]


class MockProvider:
    def __init__(self, ledger: Ledger):
        self.ledger = ledger

    # --- text (OpenRouter in the live provider) ---

    def chat_json(self, task: str, ctx: dict, feedback: str = "") -> dict:
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
        """Word timings: the expected words spread evenly, with silence at both ends."""
        self.ledger.charge("elevenlabs", f"scribe:{path.stem}",
                           PRICES["scribe_per_s"] * duration_s, mock=True)
        words = expected.split()
        step = (duration_s - 2 * EDGE_SILENCE_S) / max(len(words), 1)
        return [{"word": w, "start_s": round(EDGE_SILENCE_S + i * step, 2),
                 "end_s": round(EDGE_SILENCE_S + (i + 1) * step, 2)} for i, w in enumerate(words)]

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
            ("c1", "Honest first week", f"I almost returned this {product}."),
            ("c2", "The friend who kept asking", "My friend would not stop talking about it."),
            ("c3", "Morning routine", "This is the only step I never skip."),
            ("c4", "Before the meeting", "Ten minutes before the call, I panicked."),
            ("c5", "Unboxing", "Okay, it finally came."),
        ]
        return {"concepts": [{"id": i, "title": title, "hook": hook,
                              "insight": ctx["insights"]["pains"][0],
                              "summary": f"{title}: one person, one room, told to camera."}
                             for i, title, hook in ideas]}

    def _concept_critic(self, ctx: dict) -> dict:
        reviews = []
        for rank, concept in enumerate(ctx["concepts"]):
            score = max(9 - rank, 1)  # the first concept wins
            reviews.append({"id": concept["id"], "note": "mock score, by position in the list",
                            "scores": {"hook": score, "brief_fit": score, "platform_fit": score,
                                       "feasibility": score, "distinctiveness": score}})
        return {"reviews": reviews}

    def _look(self, ctx: dict) -> dict:
        category = ctx["brief"]["category"]
        look = {field: {"value": value, "reason": f"from the {category} playbook (mock)"}
                for field, value in ctx["playbook"].items()}
        look["cast"] = [{"name": "maya", "age": 28, "look": "woman with shoulder-length dark hair",
                         "outfit": "a plain grey t-shirt", "voice": "warm, mid-pitch (mock)"}]
        return look

    def _storyboard(self, ctx: dict) -> dict:
        brief = ctx["brief"]
        place = {"lighting": "soft window light from the left", "location": "main_location"}
        talk = {**place, "shot_type": "medium close-up", "angle": "eye level, front phone camera",
                "framing": "head and shoulders, slightly off-center", "character": "maya",
                "speaker": "maya", "camera_move": "handheld, slight sway", "route": "veo_talk",
                "dialogue_lang": brief["language"]}
        broll = {**place, "purpose": "product", "duration_s": 4, "shot_type": "close-up",
                 "angle": "top down", "framing": "product resting on a surface, off-center",
                 "first_frame": "the product stands on the surface",
                 "action": "a hand sets a towel down next to it",
                 "product_visible": True, "camera_move": "static", "route": "veo_broll"}

        def line(text: str) -> dict:
            return {"dialogue_tts": text, "dialogue_caption": text}

        shots = [
            {**talk, "id": "s01", "purpose": "hook", "duration_s": 4, "expression": "a little embarrassed",
             "first_frame": "she holds the product up near her face", "action": "she tilts it toward the lens",
             "product_visible": True, **line("Okay, I almost returned this.")},
            {**talk, "id": "s02", "purpose": "problem", "duration_s": 6, "expression": "tired, half-smile",
             "first_frame": "she looks just past the lens", "action": "she touches her cheek, then looks into the lens",
             **line("I have tried so many things, and nothing really changed.")},
            {**broll, "id": "s03"},
            {**talk, "id": "s04", "purpose": "payoff", "duration_s": 4, "expression": "relaxed smile",
             "first_frame": "she smiles at the lens", "action": "she shrugs",
             **line("Two weeks in, I get it.")},
        ]
        # Fit other target lengths: drop shots from the end, or pad with b-roll.
        while sum(s["duration_s"] for s in shots) > brief["target_length_s"] + 2:
            shots.pop()
        while sum(s["duration_s"] for s in shots) < brief["target_length_s"] - 2:
            shots.append({**broll, "id": f"s{len(shots) + 1:02d}"})
        plan = " + ".join(str(s["duration_s"]) for s in shots) + f" = {sum(s['duration_s'] for s in shots)} s"
        return {"title": ctx["concept"]["title"], "plan": plan, "shots": shots}

    def _storyboard_critic(self, ctx: dict) -> dict:
        spoken = [shot["id"] for shot in ctx["storyboard"]["shots"] if shot["dialogue_tts"]]
        return {"notes": [], "line_checks": [{"shot_id": shot_id} for shot_id in spoken],
                "storyboard": ctx["storyboard"]}

    def _edit_list(self, ctx: dict) -> dict:
        return {
            "cuts": [{"shot_id": c["shot_id"], "file": c["file"], "in_s": 0.0, "out_s": c["duration_s"],
                      "reason": "storyboard order, full take (mock)"} for c in ctx["clips"]],
            "end_card": {"line": f"Try {ctx['brief']['brand']}", "duration_s": 2.0},
        }
