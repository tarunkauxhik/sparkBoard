"""Phase 1 checks: ledger cap, full dry run, resume, approval stop. No paid calls."""
import json
from pathlib import Path

import pytest

from adgen.ledger import BudgetExceeded, Ledger
from adgen.pipeline import run_pipeline
from adgen.prompts import shot_prompt
from adgen.providers.kie import veo_payload
from adgen.providers.mock import MockProvider
from adgen.run import Run
from adgen.schemas import Brief, Look, Shot, Storyboard

BRIEF = Path(__file__).parent.parent / "briefs/skincare.json"
STEP_FILES = [
    "brief.json", "insights.json", "concepts.json", "look.json", "refs.json", "storyboard.json",
    "approval.json", "keyframes.json", "clips.json", "audio.json", "edit_list.json",
    "render.json", "qa_report.json", "decision_log.jsonl", "decision_log.md", "ledger.jsonl",
]


def dry_run(tmp_path, auto_approve=True):
    run = Run("test", root=tmp_path)
    ledger = Ledger(run.path("ledger.jsonl"))
    finished = run_pipeline(BRIEF, run, MockProvider(ledger), ledger, auto_approve)
    return run, ledger, finished


def test_ledger_refuses_to_pass_the_cap(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl", caps={"kie": 0.50})
    ledger.charge("kie", "clip 1", 0.30)
    with pytest.raises(BudgetExceeded):
        ledger.charge("kie", "clip 2", 0.30)
    assert ledger.spent("kie") == 0.30  # the refused call was not recorded


def test_ledger_remembers_spend_after_restart(tmp_path):
    Ledger(tmp_path / "ledger.jsonl").charge("kie", "clip 1", 0.30)
    assert Ledger(tmp_path / "ledger.jsonl").spent("kie") == 0.30


def test_dry_run_creates_every_file_within_the_caps(tmp_path):
    run, ledger, finished = dry_run(tmp_path)
    assert finished
    assert [name for name in STEP_FILES if not run.has(name)] == []
    for name in ("refs/maya.png", "keyframes/s01.png", "clips/raw/s01_take1.mp4", "clips/fixed/s01.mp4"):
        assert run.has(name), name
    assert all(entry["mock"] for entry in ledger.entries)
    assert 0 < ledger.spent("kie") <= ledger.caps["kie"]


def test_second_run_skips_everything(tmp_path):
    run, ledger, _ = dry_run(tmp_path)
    spent, decisions = ledger.total(), run.path("decision_log.jsonl").read_text("utf-8")
    run, ledger, finished = dry_run(tmp_path)
    assert finished
    assert ledger.total() == spent
    assert run.path("decision_log.jsonl").read_text("utf-8") == decisions


def test_stops_for_approval_without_auto_approve(tmp_path):
    run, _, finished = dry_run(tmp_path, auto_approve=False)
    assert not finished
    assert run.has("storyboard.json") and not run.has("keyframes.json")


def test_shot_rejects_a_line_too_long_for_its_duration(tmp_path):
    run, _, _ = dry_run(tmp_path, auto_approve=False)
    shot = json.loads(run.path("storyboard.json").read_text("utf-8"))["shots"][0]
    shot["dialogue_caption"] = "word " * 20  # 20 words in 6 s
    with pytest.raises(ValueError, match="too many"):
        Shot.model_validate(shot)


def test_prompt_has_the_fixed_parts_in_order(tmp_path):
    run, _, _ = dry_run(tmp_path, auto_approve=False)
    board = run.load("storyboard.json", Storyboard)
    prompt = shot_prompt(board.shots[0], board, run.load("look.json", Look), run.load("brief.json", Brief))
    labels = ["Camera:", "Subject:", "Action:", "Setting:", "Lighting:", "Dialogue:", "Audio:", "Style:", "Avoid:"]
    positions = [prompt.index(label) for label in labels]
    assert positions == sorted(positions)
    assert "phone front camera" in prompt  # UGC realism layer


def test_veo_request_never_translates_the_prompt():
    payload = veo_payload("a prompt", ["https://example.com/k.png"], "veo3_fast", 6)
    assert payload["input"]["enable_translation"] is False
