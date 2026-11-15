"""Phase 0 check: the tools the pipeline needs are present."""
import shutil
from pathlib import Path

from PIL import ImageFont

ROOT = Path(__file__).parent.parent


def test_ffmpeg_is_installed():
    assert shutil.which("ffmpeg"), "ffmpeg must be on PATH"


def test_caption_font_loads():
    font = ImageFont.truetype(str(ROOT / "assets/fonts/InterVariable.ttf"), 40)
    assert font.getname()[0].startswith("Inter")
