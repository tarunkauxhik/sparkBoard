"""Pipeline checks: ledger cap, full dry run, resume, approval stop, retries, prompts, editor."""
import json
import shutil

import pytest
from PIL import Image

from adgen.__main__ import clean, save_sample
from adgen.editor import caption_events, stream_seconds, validate_edit_list
from adgen.ledger import BudgetExceeded, Ledger
from adgen.prompts import character_sheet_prompt, keyframe_request, motion_prompt, packshot_prompt
from adgen.providers.kie import kling_avatar_payload, nano_banana_payload, veo_payload
from adgen.providers.mock import MockProvider
from adgen.schemas import Audio, Brief, EditList, Look, Refs, Storyboard
from adgen.statics import STATIC_SIZES, static_ad
from conftest import dry_run

STEP_FILES = [
    "brief.json", "insights.json", "concepts.json", "look.json", "storyboard_draft.json",
    "storyboard_critic.json", "storyboard.json", "storyboard.md", "approval.json", "refs.json",
    "keyframes.json", "clips.json", "audio.json", "edit_list.json", "render.json",
    "qa_report.json", "decision_log.jsonl", "decision_log.md", "ledger.jsonl",
]
PERSONA = "woman with shoulder-length dark hair, age 28, wearing a plain grey t-shirt"


@pytest.fixture
def story(done):
    run = done[0]
    return run.load("storyboard.json", Storyboard), run.load("look.json", Look), run.load("brief.json", Brief)


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
    for name in ("refs/maya_sheet.png", "keyframes/s01.png", "clips/raw/s01_take1.mp4", "clips/fixed/s01.mp4"):
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
                    reply["shots"][2]["duration_s"] = 5  # not a Veo length
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


def test_keyframe_prompt_names_a_role_for_every_reference_image(done, story):
    board, look, brief = story
    refs = done[0].load("refs.json", Refs)
    prompt, images = keyframe_request(board.shots[0], look, brief, refs)
    assert images == ["refs/maya_sheet.png", "refs/product.png", "refs/location.png"]
    assert "image 1 is the character sheet of maya" in prompt and "image 2 is the product" in prompt
    assert PERSONA in prompt
    assert "visible pores" in prompt                         # UGC phone look
    assert "Lens: 35 mm lens at f/2.8." in prompt            # the shot's own lens
    assert "Setting: a plain surface by a window." in prompt  # the shot's own setting
    assert "says" not in prompt                              # a still image has no dialogue
    _, silent_images = keyframe_request(board.shots[2], look, brief, refs)
    assert silent_images == ["refs/product.png", "refs/location.png"]  # b-roll: no person, no sheet


def test_motion_prompt_follows_the_veo_order(story):
    board, look, brief = story
    prompt = motion_prompt(board.shots[0], look, brief)
    parts = ["Medium close-up", "the same person as in the reference image", "[00:00-00:04]",
             'Maya says, in Indian English, neutral urban accent: "I almost returned this."',
             "Recorded close to the phone mic, dry intimate voice", "Clean frame without captions"]
    positions = [prompt.index(part) for part in parts]
    assert positions == sorted(positions)
    assert PERSONA in prompt
    assert "The delivery is quiet and plain." in prompt  # this shot's delivery, not the persona's pace
    assert "Ambient noise" not in prompt  # naming a room tone on a speaking shot made the voice echo
    silent = motion_prompt(board.shots[2], look, brief)
    assert "The scene plays without speech." in silent and "Ambient noise: quiet room tone." in silent


def test_audio_tags_are_not_read_aloud_by_veo(story):
    board, look, brief = story
    shot = board.shots[0].model_copy(update={"dialogue_tts": "[sighs] I almost returned this."})
    assert '"I almost returned this."' in motion_prompt(shot, look, brief)


def test_character_sheet_uses_the_same_persona_words(story):
    look = story[1]
    assert PERSONA in character_sheet_prompt(look.cast[0])


def test_kie_requests_match_the_docs():
    veo = veo_payload("a prompt", "https://example.com/k.png", "veo3_fast", 6)
    assert veo["model"] == "veo-3-1"
    assert veo["input"] == {
        "model": "veo3_fast", "prompt": "a prompt", "image_urls": ["https://example.com/k.png"],
        "generation_type": "FIRST_AND_LAST_FRAMES_2_VIDEO", "aspect_ratio": "9:16",
        "resolution": "720p", "duration": 6, "enable_translation": False}
    image = nano_banana_payload("a prompt", ["https://example.com/a.png"])
    assert image["model"] == "nano-banana-2-1"
    assert image["input"]["image_input"] == ["https://example.com/a.png"]
    with pytest.raises(ValueError, match="at most 10"):
        nano_banana_payload("a prompt", ["u"] * 11)
    avatar = kling_avatar_payload("she talks calmly", "https://example.com/k.png", "https://example.com/a.mp3")
    assert avatar["model"] == "kling/ai-avatar-standard"
    assert set(avatar["input"]) == {"image_url", "audio_url", "prompt"}
    for payload in (veo, image, avatar):  # Kie documents no seed field
        assert "seed" not in payload["input"] and "seeds" not in payload["input"]


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


def test_clean_keeps_runs_that_cost_real_money(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name, mock in (("dry", True), ("paid", False)):
        (tmp_path / "runs" / name).mkdir(parents=True)
        Ledger(tmp_path / "runs" / name / "ledger.jsonl").record("openrouter", "sonnet:insights", 0.01, mock=mock)
    clean(older_than_days=0, include_paid=False)
    assert [d.name for d in (tmp_path / "runs").iterdir()] == ["paid"]
    clean(older_than_days=0, include_paid=True)
    assert list((tmp_path / "runs").iterdir()) == []


def test_save_sample_copies_json_and_markdown_only(done, tmp_path, monkeypatch):
    shutil.copytree(done[0].dir, tmp_path / "runs" / "r1")
    monkeypatch.chdir(tmp_path)
    save_sample("r1", "skincare")
    saved = {f.name for f in (tmp_path / "samples/skincare").iterdir()}
    assert {"storyboard.json", "storyboard.md", "decision_log.jsonl", "ledger.jsonl"} <= saved
    assert not any(name.endswith((".mp4", ".png")) for name in saved)


def test_hands_only_shot_drops_the_character_sheet(done, story):
    board, look, brief = story
    refs = done[0].load("refs.json", Refs)
    hands = board.shots[0].model_copy(update={"face_visible": False})
    prompt, images = keyframe_request(hands, look, brief, refs)
    assert "refs/maya_sheet.png" not in images and "Person (face out of frame)" in prompt


def test_text_added_by_code_leaves_a_blank_label_area(done, story):
    board, look, brief = story
    refs = done[0].load("refs.json", Refs)
    dated = board.shots[2].model_copy(update={"blank_label_text": "ROASTED 12 NOV"})
    prompt, _ = keyframe_request(dated, look, brief, refs)
    assert "left blank and plain" in prompt and "ROASTED" not in prompt


def test_packshot_prompt_spells_out_the_whole_label(story):
    brief = story[2]
    prompt = packshot_prompt(brief)
    assert 'exactly this text and nothing else: "Dewline" and "Barrier Repair Serum".' in prompt
    earbuds = brief.model_copy(update={"brand": "Noctave", "product": "Noctave Air wireless earbuds"})
    assert 'nothing else: "Noctave".' in packshot_prompt(earbuds)  # the brand is not repeated


def test_avatar_prompt_describes_movement_and_never_the_words(story):
    from adgen.prompts import avatar_prompt
    prompt = avatar_prompt(story[0].shots[0])
    assert prompt.startswith("Maya speaks the line naturally, quiet and plain.")
    assert "I almost returned this" not in prompt  # the words come from the audio file


def test_speaker_is_only_turned_to_the_camera_when_the_eye_line_says_so(story):
    board, look, brief = story
    assert "turned toward the camera" in motion_prompt(board.shots[0], look, brief)  # looks into the lens
    away = board.shots[0].model_copy(deep=True)
    away.beats[0].eye_line = "looks at rohan off-right"
    assert "turned toward the camera" not in motion_prompt(away, look, brief)


def test_brand_accent_is_only_named_in_shots_that_show_the_product(done, story):
    board, look, brief = story
    refs = done[0].load("refs.json", Refs)
    story_brief = brief.model_copy(update={"format": "role_play"})
    accented = look.model_copy(update={"brand_accent": "one bright green on the phone screen"})
    with_product, without = board.shots[0], board.shots[1]
    assert "bright green on the phone screen" in keyframe_request(with_product, accented, story_brief, refs)[0]
    assert "bright green" not in keyframe_request(without, accented, story_brief, refs)[0]
    assert "bright green" not in motion_prompt(without, accented, story_brief)


def test_an_app_screen_is_drawn_in_code_and_named_as_a_screen_not_a_label(done, story, tmp_path):
    from adgen.schemas import AppRow, AppScreen
    from adgen.statics import app_screen
    board, look, brief = story
    app = brief.model_copy(update={"brand": "Chukta", "product": "Chukta app", "app_screen": AppScreen(
        title="Flat 4B", rows=[AppRow(name="Rohan", amount="Rs 800")], button="Pay now", color="#16c172")})
    out = tmp_path / "screen.png"
    app_screen(app, out)
    with Image.open(out) as img:
        assert img.size == (1080, 2340) and img.getpixel((10, 10)) == (0x16, 0xc1, 0x72)  # the brand bar
    prompt, _ = keyframe_request(board.shots[0], look, app, done[0].load("refs.json", Refs))
    assert "the Chukta app screen: show it on the phone display" in prompt
    assert "keep its shape, color and label" not in prompt and "apart from the app screen on the phone" in prompt
