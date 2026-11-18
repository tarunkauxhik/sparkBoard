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
from adgen.pipeline import run_pipeline
from adgen.providers.mock import MockProvider
from adgen.run import Run
from adgen.schemas import Audio, Brief, EditList, Look, Refs, Storyboard
from adgen.statics import STATIC_SIZES, static_ad
from conftest import BRIEF, dry_run

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
    for name in ("refs/maya_sheet.png", "keyframes/s01_take1.png", "clips/raw/s01_take1.mp4", "clips/fixed/s01.mp4"):
        assert run.has(name), name
    assert all(entry["mock"] for entry in ledger.entries)
    assert 0 < ledger.spent("kie") <= ledger.caps["kie"]
    assert json.loads(run.path("qa_report.json").read_text("utf-8"))["passed"]


def test_final_video_has_the_right_length(done):
    run = done[0]
    final = run.dir / "final/ad_9x16.mp4"
    # Spoken shots are trimmed to their words plus 0.4 s each side: 3.8 + 5.8 + 4 (silent) + 3.8 s,
    # rounded to whole frames, plus a 2 s end card.
    assert stream_seconds(final, "v:0") == pytest.approx(19.375, abs=0.05)
    assert stream_seconds(final, "a:0") == pytest.approx(19.375, abs=0.03)
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
    # shot 3 is silent b-roll at about 9.58-13.58 s; shot 4's first word comes 0.4 s into its cut
    assert not any(9.59 < start < 13.58 for start, _, _ in events)
    assert any(start == pytest.approx(13.983, abs=0.01) for start, _, _ in events)


def test_static_ads_come_out_in_every_size(done, tmp_path):
    keyframe = done[0].dir / "keyframes/s01_take1.png"
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


def test_save_sample_copies_json_markdown_and_the_final_video(done, tmp_path, monkeypatch):
    shutil.copytree(done[0].dir, tmp_path / "runs" / "r1")
    monkeypatch.chdir(tmp_path)
    save_sample("r1", "skincare")
    saved = {f.name for f in (tmp_path / "samples/skincare").iterdir()}
    assert {"storyboard.json", "storyboard.md", "decision_log.jsonl", "ledger.jsonl", "ad_9x16.mp4"} <= saved
    assert not any("take" in name for name in saved)  # raw takes and keyframes stay in runs/


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


# ---------------- phase 5: retry loops, trims, final checks ----------------

def test_a_keyframe_that_fails_the_face_check_is_made_again(tmp_path):
    class FirstFaceIsWrong(MockProvider):
        def __init__(self, ledger):
            super().__init__(ledger)
            scores = iter([0.30, 0.80] + [0.90] * 50)  # s01 take 1 fails, take 2 passes
            self.faces.similarity = lambda sheet, frame: next(scores)

    run, _, finished = dry_run(tmp_path, provider_cls=FirstFaceIsWrong)
    keyframes = json.loads(run.path("keyframes.json").read_text("utf-8"))
    s01 = [(t["take"], t["passed"]) for t in keyframes["takes"] if t["shot_id"] == "s01"]
    assert s01 == [(1, False), (2, True)] and keyframes["files"]["s01"] == "keyframes/s01_take2.png"
    assert run.has("keyframes/s01_take1.png")  # the failed take is kept, never overwritten
    assert finished and json.loads(run.path("qa_report.json").read_text("utf-8"))["passed"]


def test_a_clip_with_wrong_words_gets_one_more_take_and_is_then_flagged(tmp_path):
    class NeverSaysTheLastWord(MockProvider):
        def transcribe(self, path, expected, duration_s):
            words = super().transcribe(path, expected, duration_s)
            return words[:-1] if path.stem.startswith("s01") else words

    run, ledger, finished = dry_run(tmp_path, provider_cls=NeverSaysTheLastWord)
    takes = [t for t in json.loads(run.path("clips.json").read_text("utf-8"))["takes"] if t["shot_id"] == "s01"]
    assert [t["take"] for t in takes] == [1, 2]            # two tries, never a third
    assert "words:" in takes[1]["problems"][0]
    report = json.loads(run.path("qa_report.json").read_text("utf-8"))
    flagged = [c for c in report["checks"] if c["name"] == "clip s01 passed its checks"]
    assert finished and not report["passed"] and flagged and "words:" in flagged[0]["detail"]


def test_a_live_run_can_stop_after_a_stage_and_continue_later(tmp_path):
    run = Run("test", root=tmp_path)
    ledger = Ledger(run.path("ledger.jsonl"))
    provider = MockProvider(ledger)
    assert not run_pipeline(BRIEF, run, provider, ledger, True, stop_after="keyframes")
    assert run.has("keyframes.json") and not run.has("clips.json")
    assert run_pipeline(BRIEF, run, provider, ledger, True)
    assert run.has("qa_report.json")


def test_the_voice_isolator_is_only_used_when_asked(tmp_path):
    run = Run("test", root=tmp_path)
    ledger = Ledger(run.path("ledger.jsonl"))
    assert run_pipeline(BRIEF, run, MockProvider(ledger), ledger, True, isolate_voice=True)
    assert run.has("clips/fixed/s01_voice.mp3") and not run.has("clips/fixed/s03_voice.mp3")  # s03 is silent
    assert sum("isolate" in entry["item"] for entry in ledger.entries) == 3
    assert json.loads(run.path("qa_report.json").read_text("utf-8"))["passed"]


def test_edit_list_trims_spoken_clips_to_their_words(done):
    run = done[0]
    cuts = {cut.shot_id: cut for cut in run.load("edit_list.json", EditList).cuts}
    assert (cuts["s01"].in_s, cuts["s01"].out_s) == (0.1, 3.9)     # words run 0.5 to 3.5 s; 0.4 s pad
    assert (cuts["s03"].in_s, cuts["s03"].out_s) == (0.0, 4.0)     # silent: the full take
    assert run.load("edit_list.json", EditList).end_card.line == run.load("storyboard.json", Storyboard).end_card_line


def test_pitch_of_a_known_tone(done):
    from adgen.voice import median_pitch_hz
    pitch = median_pitch_hz(done[0].dir / "clips/raw/s01_take1.mp4", 0.5, 3.5)  # the mock clip is a 220 Hz tone
    assert pitch == pytest.approx(220, abs=5)


def test_live_provider_uploads_each_reference_once(tmp_path):
    from adgen.providers.live import LiveProvider

    class FakeKie:
        uploads, tasks = [], []

        def upload(self, path):
            self.uploads.append(path.name)
            return f"https://files.example/{path.name}"

        def run_task(self, name, payload, assumed_usd, out):
            self.tasks.append((name, payload["input"].get("image_input")))
            return {"task_id": "t1"}

    provider = LiveProvider.__new__(LiveProvider)  # no keys, no network: only the Kie part is exercised
    provider.kie, provider.uploaded, provider.run = FakeKie(), {}, Run("r", root=tmp_path)
    sheet = tmp_path / "r" / "refs" / "maya_sheet.png"
    provider.image("first", [sheet], tmp_path / "r" / "keyframes" / "s01_take1.png")
    provider.image("second", [sheet], tmp_path / "r" / "keyframes" / "s02_take1.png")
    assert provider.kie.uploads == ["maya_sheet.png"]
    assert [name for name, _ in provider.kie.tasks] == ["keyframes_s01_take1", "keyframes_s02_take1"]
    assert provider.kie.tasks[0][1] == ["https://files.example/maya_sheet.png"]


def test_trim_pad_is_a_setting(done):
    from adgen.editor import build_edit_list
    run = done[0]
    audio = run.load("audio.json", Audio)
    durations = {clip.shot_id: 4.0 if clip.shot_id != "s02" else 6.0 for clip in audio.clips}
    tight = {c.shot_id: (c.in_s, c.out_s) for c in build_edit_list(audio, durations, "Try it", pad=0.15).cuts}
    assert tight["s01"] == (0.35, 3.65)
    wide = {c.shot_id: (c.in_s, c.out_s) for c in build_edit_list(audio, durations, "Try it", pad=1.0).cuts}
    assert wide["s01"] == (0.0, 4.0)  # never past the ends of the clip


def test_final_qa_checks_for_clicks_between_words(done):
    report = json.loads(done[0].path("qa_report.json").read_text("utf-8"))
    clicks = [c for c in report["checks"] if c["name"].startswith("no clicks or taps between the words")]
    assert len(clicks) == 3 and all(c["passed"] for c in clicks)  # three spoken shots, mock audio is a clean tone


def test_end_card_shows_the_product_above_the_brand(done, tmp_path):
    from adgen.statics import end_card
    plain, with_product = tmp_path / "plain.png", tmp_path / "product.png"
    end_card("Dewline", "Made for sensitive skin.", plain)
    end_card("Dewline", "Made for sensitive skin.", with_product, done[0].dir / "refs/product.png")
    with Image.open(plain) as a, Image.open(with_product) as b:
        assert a.getpixel((540, 500)) == (20, 20, 20)       # plain: the top is the dark background
        assert b.getpixel((540, 500)) != (20, 20, 20)       # with product: the product card is there


def test_label_text_is_written_into_the_blank_area(done, tmp_path):
    from adgen.statics import write_label
    keyframe, out = done[0].dir / "keyframes/s01_take1.png", tmp_path / "labelled.png"
    write_label(keyframe, "ROASTED 12 NOV", (0.30, 0.40, 0.70, 0.46), out)
    with Image.open(keyframe) as before, Image.open(out) as after:
        box = (330, 780, 750, 880)
        assert before.crop(box).tobytes() != after.crop(box).tobytes()          # text was drawn there
        assert before.crop((0, 0, 200, 200)).tobytes() == after.crop((0, 0, 200, 200)).tobytes()  # rest untouched


def test_a_shot_with_label_text_gets_a_labelled_keyframe(tmp_path):
    class LabelledShot(MockProvider):
        def chat_json(self, task, ctx, feedback=""):
            reply = super().chat_json(task, ctx, feedback)
            if task == "storyboard":
                reply["shots"][2]["blank_label_text"] = "ROASTED 12 NOV"  # the silent product shot
            return reply

    run, _, finished = dry_run(tmp_path, provider_cls=LabelledShot)
    keyframes = json.loads(run.path("keyframes.json").read_text("utf-8"))
    assert finished and keyframes["files"]["s03"] == "keyframes/s03_labelled.png"
    assert "wrote 'ROASTED 12 NOV'" in run.path("decision_log.md").read_text("utf-8")


def test_label_area_box_rejects_nonsense():
    from adgen.qa import LabelArea
    assert LabelArea(found=True, left=300, top=400, right=700, bottom=460).box() == (0.3, 0.4, 0.7, 0.46)
    assert LabelArea(found=True, left=700, top=400, right=300, bottom=460).box() is None
    assert LabelArea(found=False, left=0, top=0, right=0, bottom=0).box() is None


# ---------------- narrator voice, stop on failure, blank products ----------------

def test_voiceover_shots_get_a_narrator_line_laid_over_the_clip(tmp_path):
    from conftest import dry_run as run_brief
    import adgen.pipeline as pipeline_module
    run = Run("vo", root=tmp_path)
    ledger = Ledger(run.path("ledger.jsonl"))
    coffee = BRIEF.parent / "coffee.json"
    assert run_pipeline(coffee, run, MockProvider(ledger), ledger, True)
    takes = {t["shot_id"]: t for t in json.loads(run.path("clips.json").read_text("utf-8"))["takes"]}
    narrated = [t for t in takes.values() if t["voice_file"]]
    assert narrated and all(t["words"][0]["start_s"] >= pipeline_module.VO_START_S for t in narrated)
    assert any("tts:" in entry["item"] for entry in ledger.entries)
    fixed = run.dir / "clips/fixed" / f"{narrated[0]['shot_id']}.mp4"
    assert stream_seconds(fixed, "a:0") == pytest.approx(stream_seconds(fixed, "v:0"), abs=0.05)


def test_a_bad_narrator_line_does_not_cause_a_new_clip(tmp_path):
    class GarbledNarrator(MockProvider):
        def transcribe(self, path, expected, duration_s):
            words = super().transcribe(path, expected, duration_s)
            return words[:1] if path.parent.name == "voice" else words  # the TTS line comes back short

    run = Run("vo", root=tmp_path)
    ledger = Ledger(run.path("ledger.jsonl"))
    assert run_pipeline(BRIEF.parent / "coffee.json", run, GarbledNarrator(ledger), ledger, True)
    narrated = [t for t in json.loads(run.path("clips.json").read_text("utf-8"))["takes"] if t["voice_file"]]
    assert all(t["take"] == 1 for t in narrated)               # no retake: a new clip cannot fix the voice
    assert all(t["problems"][0].startswith("words:") for t in narrated)


def test_stop_on_failure_stops_after_clips_when_a_shot_fails_every_take(tmp_path):
    class NeverSaysTheLastWord(MockProvider):
        def transcribe(self, path, expected, duration_s):
            words = super().transcribe(path, expected, duration_s)
            return words[:-1] if path.stem.startswith("s01") else words

    run = Run("stop", root=tmp_path)
    ledger = Ledger(run.path("ledger.jsonl"))
    assert not run_pipeline(BRIEF, run, NeverSaysTheLastWord(ledger), ledger, True, stop_on_failure=True)
    assert run.has("clips.json") and not run.has("audio.json")


def test_every_keyframe_asks_for_blank_labels_on_other_products(done, story):
    board, look, brief = story
    refs = done[0].load("refs.json", Refs)
    for shot in board.shots:
        assert "plain blank label and no readable words, logos or brand names" in keyframe_request(shot, look, brief, refs)[0]


def test_captions_show_the_roman_line_on_the_transcript_timing():
    from adgen.editor import caption_words
    from adgen.schemas import Word
    heard = [Word(word="कल", start_s=0.3, end_s=0.5), Word(word="दे", start_s=0.5, end_s=0.6),
             Word(word="दूँगा,", start_s=0.6, end_s=1.0), Word(word="पक्का।", start_s=1.1, end_s=1.6)]
    same_count = caption_words(heard, "Kal de dunga, pakka.")
    assert [w.word for w in same_count] == ["Kal", "de", "dunga,", "pakka."] and same_count[3].start_s == 1.1
    different = caption_words(heard, "Kal de dunga pakka yaar")  # five words over the same span
    assert [w.word for w in different][-1] == "yaar" and different[0].start_s == 0.3 and different[-1].end_s == 1.6


def narrated_takes(tmp_path, extra_words: str) -> tuple[Run, list[dict]]:
    class LongLines(MockProvider):
        def speak(self, text, out, voice_id, speed=1.0):
            super().speak(text + extra_words, out, voice_id, speed)  # the mock's lines, made longer

    run = Run("vo", root=tmp_path)
    ledger = Ledger(run.path("ledger.jsonl"))
    run_pipeline(BRIEF.parent / "coffee.json", run, LongLines(ledger), ledger, True)
    takes = [t for t in json.loads(run.path("clips.json").read_text("utf-8"))["takes"] if t["voice_file"]]
    return run, [t for t in takes if t["shot_id"] in ("s01", "s04")]  # the two 4 s narrated shots


def test_a_narrator_line_that_fits_when_started_early_is_not_sped_up(tmp_path):
    run, takes = narrated_takes(tmp_path, " and more")         # 3.4 s: too long from 0.5 s, fine from 0.15 s
    assert all(not t["voice_file"].endswith("_faster.mp3") and t["voice_start_s"] < 0.5 for t in takes)
    assert all(not t["problems"] for t in takes)


def test_a_long_narrator_line_is_spoken_faster(tmp_path):
    run, takes = narrated_takes(tmp_path, " and a bit more")  # 4.2 s: needs about 1.16x
    assert all(t["voice_file"].endswith("_faster.mp3") for t in takes)
    for take in takes:  # the line now ends inside the shot
        assert take["voice_start_s"] + stream_seconds(run.dir / take["voice_file"], "a:0") <= 3.9
        assert not take["problems"]
