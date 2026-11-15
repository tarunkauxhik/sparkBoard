"""Pipeline checks: ledger cap, full dry run, resume, approval stop, editor. No paid calls."""
import json
from pathlib import Path

import pytest
from PIL import Image

from adgen.editor import caption_events, stream_seconds, validate_edit_list
from adgen.ledger import BudgetExceeded, Ledger
from adgen.pipeline import run_pipeline
from adgen.prompts import shot_prompt
from adgen.providers.kie import veo_payload
from adgen.providers.mock import MockProvider
from adgen.run import Run
from adgen.schemas import Audio, Brief, EditList, Look, Shot, Storyboard
from adgen.statics import STATIC_SIZES, static_ad

BRIEF = Path(__file__).parent.parent / "briefs/skincare.json"
STEP_FILES = [
    "brief.json", "insights.json", "concepts.json", "look.json", "refs.json", "storyboard.json",
    "approval.json", "keyframes.json", "clips.json", "audio.json", "edit_list.json",
    "render.json", "qa_report.json", "decision_log.jsonl", "decision_log.md", "ledger.jsonl",
]


def dry_run(root, auto_approve=True):
    run = Run("test", root=root)
    ledger = Ledger(run.path("ledger.jsonl"))
    finished = run_pipeline(BRIEF, run, MockProvider(ledger), ledger, auto_approve)
    return run, ledger, finished


@pytest.fixture(scope="module")
def done(tmp_path_factory):
    """One finished dry run, shared by the tests that only read it."""
    return dry_run(tmp_path_factory.mktemp("runs"))


def test_ledger_refuses_to_pass_the_cap(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl", caps={"kie": 0.50})
    ledger.charge("kie", "clip 1", 0.30)
    with pytest.raises(BudgetExceeded):
        ledger.charge("kie", "clip 2", 0.30)
    assert ledger.spent("kie") == 0.30  # the refused call was not recorded


def test_ledger_remembers_spend_after_restart(tmp_path):
    Ledger(tmp_path / "ledger.jsonl").charge("kie", "clip 1", 0.30)
    assert Ledger(tmp_path / "ledger.jsonl").spent("kie") == 0.30


def test_dry_run_creates_every_file_within_the_caps(done):
    run, ledger, finished = done
    assert finished
    assert [name for name in STEP_FILES if not run.has(name)] == []
    for name in ("refs/maya.png", "keyframes/s01.png", "clips/raw/s01_take1.mp4", "clips/fixed/s01.mp4"):
        assert run.has(name), name
    assert all(entry["mock"] for entry in ledger.entries)
    assert 0 < ledger.spent("kie") <= ledger.caps["kie"]
    assert json.loads(run.path("qa_report.json").read_text("utf-8"))["passed"]


def test_final_video_has_the_right_shape_and_length(done):
    run = done[0]
    final = run.dir / "final/ad_9x16.mp4"
    # 3 talking shots of 6 s + one 4 s b-roll + a 2 s end card
    assert stream_seconds(final, "v:0") == pytest.approx(24.0, abs=0.05)
    assert stream_seconds(final, "a:0") == pytest.approx(24.0, abs=0.03)
    assert not run.has("work")  # temp folder is removed after the render


def test_second_run_skips_everything(done):
    run, ledger, _ = done
    spent, decisions = ledger.total(), run.path("decision_log.jsonl").read_text("utf-8")
    run, ledger, finished = dry_run(run.dir.parent)
    assert finished
    assert ledger.total() == spent
    assert run.path("decision_log.jsonl").read_text("utf-8") == decisions


def test_stops_for_approval_without_auto_approve(tmp_path):
    run, _, finished = dry_run(tmp_path, auto_approve=False)
    assert not finished
    assert run.has("storyboard.json") and not run.has("keyframes.json")


def test_shot_rejects_a_line_too_long_for_its_duration(done):
    shot = json.loads(done[0].path("storyboard.json").read_text("utf-8"))["shots"][0]
    shot["dialogue_caption"] = "word " * 20  # 20 words in 6 s
    with pytest.raises(ValueError, match="too many"):
        Shot.model_validate(shot)


def test_prompt_has_the_fixed_parts_in_order(done):
    run = done[0]
    board = run.load("storyboard.json", Storyboard)
    prompt = shot_prompt(board.shots[0], board, run.load("look.json", Look), run.load("brief.json", Brief))
    labels = ["Camera:", "Subject:", "Action:", "Setting:", "Lighting:", "Dialogue:", "Audio:", "Style:", "Avoid:"]
    positions = [prompt.index(label) for label in labels]
    assert positions == sorted(positions)
    assert "phone front camera" in prompt  # UGC realism layer


def test_veo_request_never_translates_the_prompt():
    payload = veo_payload("a prompt", ["https://example.com/k.png"], "veo3_fast", 6)
    assert payload["input"]["enable_translation"] is False


def test_validator_catches_bad_cuts(done):
    run = done[0]
    edit, audio = run.load("edit_list.json", EditList), run.load("audio.json", Audio)
    assert validate_edit_list(edit, audio, run) == []
    edit.cuts[0].out_s = 3.1          # inside a word of shot 1
    edit.cuts[1].file = "clips/fixed/missing.mp4"
    edit.cuts[2].out_s = 99           # past the end of the clip
    errors = "\n".join(validate_edit_list(edit, audio, run))
    assert "inside the word" in errors and "does not exist" in errors and "outside the clip" in errors


def test_captions_are_short_and_follow_the_timeline(done):
    run = done[0]
    events = caption_events(run.load("edit_list.json", EditList), run.load("audio.json", Audio))
    assert all(len(text.split()) <= 4 for _, _, text in events)
    assert [start for start, _, _ in events] == sorted(start for start, _, _ in events)
    # shot 3 is silent b-roll at 12-16 s, so no caption may sit there; shot 4 starts at 16 s
    assert not any(12 < start < 16 for start, _, _ in events)
    assert any(start == pytest.approx(16.0) for start, _, _ in events)


def test_static_ads_come_out_in_every_size(done, tmp_path):
    keyframe = done[0].dir / "keyframes/s01.png"
    for name, size in STATIC_SIZES.items():
        out = tmp_path / f"{name}.png"
        static_ad(keyframe, "Skin that finally calms down", "Dewline", size, out)
        with Image.open(out) as img:
            assert img.size == size
