"""Pipeline checks: ledger cap, full dry run, resume, approval stop, retries, editor."""
import json

import pytest
from PIL import Image

from adgen.editor import caption_events, stream_seconds, validate_edit_list
from adgen.ledger import BudgetExceeded, Ledger
from adgen.prompts import keyframe_prompt, motion_prompt
from adgen.providers.kie import veo_payload
from adgen.providers.mock import MockProvider
from adgen.schemas import Audio, Brief, EditList, Look, Storyboard
from adgen.statics import STATIC_SIZES, static_ad
from conftest import dry_run

STEP_FILES = [
    "brief.json", "insights.json", "concepts.json", "look.json", "storyboard_draft.json",
    "storyboard_critic.json", "storyboard.json", "storyboard.md", "approval.json", "refs.json",
    "keyframes.json", "clips.json", "audio.json", "edit_list.json", "render.json",
    "qa_report.json", "decision_log.jsonl", "decision_log.md", "ledger.jsonl",
]


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


def test_final_video_has_the_right_length(done):
    run = done[0]
    final = run.dir / "final/ad_9x16.mp4"
    # shots of 4 + 6 + 4 + 4 s, plus a 2 s end card
    assert stream_seconds(final, "v:0") == pytest.approx(20.0, abs=0.05)
    assert stream_seconds(final, "a:0") == pytest.approx(20.0, abs=0.03)
    assert not run.has("work")  # temp folder is removed after the render


def test_second_run_skips_everything(done):
    run, ledger, _ = done
    spent, decisions = ledger.total(), run.path("decision_log.jsonl").read_text("utf-8")
    run, ledger, finished = dry_run(run.dir.parent)
    assert finished
    assert ledger.total() == spent
    assert run.path("decision_log.jsonl").read_text("utf-8") == decisions


def test_stops_for_approval_before_any_image_is_made(tmp_path):
    run, ledger, finished = dry_run(tmp_path, auto_approve=False)
    assert not finished
    assert run.has("storyboard.md") and not run.has("refs.json")
    assert ledger.spent("kie") == 0


def test_a_rejected_reply_is_retried_once_with_the_errors(tmp_path):
    class BadFirstStoryboard(MockProvider):
        feedback_seen = []

        def chat_json(self, task, ctx, feedback=""):
            reply = super().chat_json(task, ctx, feedback)
            if task == "storyboard":
                self.feedback_seen.append(feedback)
                if not feedback:
                    reply["shots"][1]["duration_s"] = 5  # not a Veo length
            return reply

    run, _, finished = dry_run(tmp_path, provider_cls=BadFirstStoryboard)
    assert finished
    assert len(BadFirstStoryboard.feedback_seen) == 2
    assert "4, 6 or 8" in BadFirstStoryboard.feedback_seen[1]


def test_schema_retries_stop_after_two_tries(tmp_path):
    class AlwaysBad(MockProvider):
        calls = 0

        def chat_json(self, task, ctx, feedback=""):
            AlwaysBad.calls += 1
            return {}

    with pytest.raises(ValueError, match="after 2 tries"):
        dry_run(tmp_path, provider_cls=AlwaysBad)
    assert AlwaysBad.calls == 2


def test_each_shot_has_a_keyframe_prompt_and_a_motion_prompt(done):
    run = done[0]
    board, look, brief = (run.load("storyboard.json", Storyboard), run.load("look.json", Look),
                          run.load("brief.json", Brief))
    still, motion = keyframe_prompt(board.shots[0], look, brief), motion_prompt(board.shots[0])
    assert "phone front camera" in still and "Dialogue:" not in still  # UGC realism layer, no speech
    assert "woman with shoulder-length dark hair" in still             # cast look, word for word
    assert 'says, in Indian English: "Okay, I almost returned this."' in motion
    assert "No one speaks" in motion_prompt(board.shots[2])            # the silent b-roll shot


def test_veo_request_never_translates_the_prompt():
    payload = veo_payload("a prompt", ["https://example.com/k.png"], "veo3_fast", 6)
    assert payload["input"]["enable_translation"] is False


def test_validator_catches_bad_cuts(done):
    run = done[0]
    edit, audio = run.load("edit_list.json", EditList), run.load("audio.json", Audio)
    assert validate_edit_list(edit, audio, run) == []
    edit.cuts[0].out_s = 3.1          # inside the last word of shot 1
    edit.cuts[1].file = "clips/fixed/missing.mp4"
    edit.cuts[2].out_s = 99           # past the end of the clip
    errors = "\n".join(validate_edit_list(edit, audio, run))
    assert "inside the word" in errors and "does not exist" in errors and "outside the clip" in errors


def test_captions_are_short_and_follow_the_timeline(done):
    run = done[0]
    events = caption_events(run.load("edit_list.json", EditList), run.load("audio.json", Audio))
    assert all(len(text.split()) <= 4 for _, _, text in events)
    assert [start for start, _, _ in events] == sorted(start for start, _, _ in events)
    # shot 3 is silent b-roll at 10-14 s; shot 4 starts at 14 s and speaks after 0.5 s of silence
    assert not any(10 < start < 14 for start, _, _ in events)
    assert any(start == pytest.approx(14.5) for start, _, _ in events)


def test_static_ads_come_out_in_every_size(done, tmp_path):
    keyframe = done[0].dir / "keyframes/s01.png"
    for name, size in STATIC_SIZES.items():
        out = tmp_path / f"{name}.png"
        static_ad(keyframe, "Skin that finally calms down", "Dewline", size, out)
        with Image.open(out) as img:
            assert img.size == size
