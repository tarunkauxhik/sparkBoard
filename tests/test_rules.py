"""Storyboard and cast rules that are checked in code."""
import pytest

from adgen.qa import ClipScores, word_error_rate, words_pass
from adgen.casting import casting_errors, look_similarity, used_personas
from adgen.ledger import Ledger
from adgen.rules import look_errors, review_errors, storyboard_errors
from adgen.schemas import (
    Brief, CastMember, Claim, CriticNote, LineCheck, Look, Shot, Storyboard, StoryboardReview, max_words,
)


@pytest.fixture
def parts(done):
    run = done[0]
    return run.load("storyboard.json", Storyboard), run.load("brief.json", Brief), run.load("look.json", Look)


def changed_shot(board: Storyboard, index: int, **changes) -> dict:
    return {**board.shots[index].model_dump(), **changes}


def with_shot(board: Storyboard, index: int, **changes) -> Storyboard:
    shots = [shot.model_dump() for shot in board.shots]
    shots[index] = changed_shot(board, index, **changes)
    return Storyboard.model_validate({**board.model_dump(), "shots": shots})


def test_the_mock_storyboard_passes(parts):
    assert storyboard_errors(*parts) == []


def test_word_limits_leave_silence_at_both_ends():
    assert (max_words(4), max_words(6), max_words(8)) == (6, 11, 15)


@pytest.mark.parametrize("changes, message", [
    ({"dialogue_caption": "word " * 16}, "too long for one shot"),
    ({"dialogue_caption": "सुबह से thakaan"}, "Roman script"),
    ({"dialogue_caption": "[sighs] so tired"}, "no audio tags"),
    ({"dialogue_tts": "[sighs] so [laughs] tired"}, "one audio tag"),
    ({"dialogue_lang": ""}, "dialogue_lang"),
    ({"delivery": ""}, "delivery"),
    ({"dialogue_caption": "I love it so much!"}, "exclamation"),
    ({"lens": "85 mm at f/2 or a 100 mm macro"}, "exactly one lens"),
    ({"shot_type": "wide shot"}, "medium close-up"),
    ({"camera_move": "fast dolly in"}, "static' or 'light handheld"),
    ({"speaker": "someone_else"}, "speaker is the person on screen"),
    ({"route": "veo_broll"}, "silent"),
    ({"beats": []}, "1 or 2 beats"),
    ({"beats": [{"start_s": 0, "end_s": 9, "action": "she nods", "eye_line": "looks into the lens"}]},
     "outside the shot"),
    ({"beats": [{"start_s": 0, "end_s": 3, "action": "she nods"}]}, "eye_line"),
])
def test_shot_rules(parts, changes, message):
    with pytest.raises(ValueError, match=message):
        Shot.model_validate(changed_shot(parts[0], 1, **changes))  # shot 2: a 6 s talking shot


def test_code_sets_the_duration_from_its_own_word_count(parts):
    board = parts[0]
    longer = Shot.model_validate(changed_shot(board, 0, dialogue_caption="Watch my face when I put this on."))
    assert longer.duration_s == 6  # 8 words do not fit the 4 s the writer asked for
    shorter = Shot.model_validate(changed_shot(board, 1, dialogue_caption="Nothing yet."))
    assert shorter.duration_s == 4 and shorter.beats[0].end_s == 4  # the beat moves with the shot
    hinglish = Shot.model_validate(changed_shot(board, 0, dialogue_caption="Rohan ke 800 rupaye pending hain yaar."))
    assert hinglish.words == 7 and hinglish.duration_s == 6


def test_plan_is_rewritten_by_code_with_the_real_counts(parts):
    board = parts[0]
    lied = Storyboard.model_validate({**board.model_dump(), "plan": "s01 2 words = 4 s; total 10 s"})
    assert lied.plan == "s01 4 words = 4 s; s02 10 words = 6 s; s03 silent = 4 s; s04 4 words = 4 s; total 18 s"


def test_rejections_carry_the_real_counts(parts):
    board, brief, look = parts
    errors = storyboard_errors(with_shot(board, 3, purpose="payoff"), brief, look)
    assert errors[-1].startswith("Real counts, measured by code") and "total 18 s" in errors[-1]


def test_cast_must_be_adult_not_a_likeness_and_have_speech_habits(parts):
    member = parts[2].cast[0].model_dump()
    CastMember.model_validate(member)
    with pytest.raises(ValueError, match="25 or older"):
        CastMember.model_validate({**member, "age": 19})
    with pytest.raises(ValueError, match="likeness"):
        CastMember.model_validate({**member, "look": "resembles a famous film star"})
    CastMember.model_validate({**member, "look": "looks like someone with sensitive skin"})  # not a likeness
    with pytest.raises(ValueError):
        CastMember.model_validate({**member, "speech_habits": ["only one"]})


@pytest.mark.parametrize("index, changes, message", [
    (1, {"character": "riya", "speaker": "riya"}, "not in the cast"),
    (2, {"duration_s": 8, "beats": [{"start_s": 0, "end_s": 8, "action": "a hand moves"}]}, "add up to"),
    (0, {"duration_s": 6, "dialogue_caption": "this hook line just keeps going on and on"}, "hook line"),
    (0, {"dialogue_caption": "Okay, I almost returned this."}, "warm-up word"),
    (0, {"product_visible": False}, "visible in shot 1"),
    (1, {"dialogue_caption": "honestly this is a game changer"}, "overused"),
    (1, {"first_frame": "her kid stands next to her"}, "no children"),
    (1, {"lighting": "a ring light in front of her"}, "ring light"),
    (1, {"lighting": "low evening sun through the window, warm table lamp as fill"}, "one light source"),
    (1, {"lighting": "window daylight and a warm lamp"}, "one light source"),
    (1, {"lens": "iPhone 15 main camera, 24mm equivalent, f/1.78"}, "real phone, camera or lens brand"),
    (1, {"first_frame": "a flawless cinematic portrait"}, "cinematic"),
    (3, {"purpose": "payoff"}, "call to action"),
])
def test_storyboard_rules(parts, index, changes, message):
    board, brief, look = parts
    assert message in "\n".join(storyboard_errors(with_shot(board, index, **changes), brief, look))


def test_ugc_needs_a_broll_shot_and_product_hero_needs_a_static(parts):
    board, brief, look = parts
    talking = {**board.shots[0].model_dump(), "id": "s03", "purpose": "proof"}  # a 4 s talking shot
    assert "veo_broll" in "\n".join(storyboard_errors(with_shot(board, 2, **talking), brief, look))
    product_ad = brief.model_copy(update={"format": "product_hero"})
    assert "static shot" in "\n".join(storyboard_errors(board, product_ad, look))


def test_look_rejects_glossy_words(parts):
    brief, look = parts[1], parts[2]
    assert look_errors(look, brief) == []
    glossy = look.model_copy(update={"lens": look.lens.model_copy(update={"value": "8K cinematic lens"})})
    assert "cinematic" in "\n".join(look_errors(glossy, brief))
    branded = look.model_copy(update={"camera": look.camera.model_copy(update={"value": "shot on a Sony FX3"})})
    assert "brand" in "\n".join(look_errors(branded, brief))
    story = brief.model_copy(update={"format": "brand_story"})
    assert "add a narrator" in "\n".join(look_errors(look, story))  # a narrator format with no narrator


def test_every_claim_in_every_spoken_line_needs_a_backing_fact(parts):
    board, brief, look = parts
    spoken = [shot.id for shot in board.shots if shot.dialogue_tts]

    def errors(line_checks):
        review = StoryboardReview(notes=[], line_checks=line_checks, storyboard=board)
        return "\n".join(review_errors(review, brief, look))

    none = [LineCheck(shot_id=shot_id) for shot_id in spoken] + [LineCheck(shot_id="end_card")]
    backed = [Claim(claim="no fragrance", fact=0), Claim(claim="for sensitive skin", fact=3)]
    assert errors(none) == ""
    assert "no entry" in errors(none[1:])
    assert errors([none[0], LineCheck(shot_id=spoken[1], claims=backed), *none[2:]]) == ""
    invented = LineCheck(shot_id=spoken[1], claims=[backed[0], Claim(claim="full refund")])
    assert "full refund" in errors([none[0], invented, *none[2:]])
    out_of_range = LineCheck(shot_id=spoken[1], claims=[Claim(claim="x", fact=99)])
    assert "not backed" in errors([none[0], out_of_range, *none[2:]])
    hook_claim = LineCheck(shot_id=spoken[0], claims=[backed[0]])
    assert "hook must not make product claims" in errors([hook_claim, *none[1:]])


def test_word_error_rate_and_rubric():
    script = "Watch my face when I put this on"
    assert word_error_rate(script, "watch my face when I put this on.") == 0
    assert word_error_rate(script, "watch my face when I put this") == pytest.approx(1 / 8)  # last word cut off
    assert words_pass(script, script) and not words_pass(script, "watch my face when I put this")
    assert word_error_rate("कल दे दूँगा, पक्का।", "कल दे दूँगा पक्का") == 0      # Hindi words stay whole
    assert word_error_rate("कल दे दूँगा, पक्का।", "कल दे दूँगा") == pytest.approx(1 / 4)
    good = ClipScores(hands=4, label=5, lip_sync=3, ai_look=4, hook_strength=3)
    assert not good.needs_reroll()
    assert good.model_copy(update={"hands": 2}).needs_reroll()


def voiceover_board(board: Storyboard) -> Storyboard:
    """The mock UGC board turned into a narrator ad: every talking shot becomes voiceover."""
    shots = [{**shot.model_dump(), "route": "vo_only", "character": None, "speaker": "narrator",
              "shot_type": "close-up", "camera_move": "static"} if shot.route == "veo_talk" else shot.model_dump()
             for shot in board.shots]
    return Storyboard.model_validate({**board.model_dump(), "shots": shots})


def test_narrator_formats_use_voiceover_with_at_most_one_on_camera_line(parts):
    board, brief, look = parts
    story = brief.model_copy(update={"format": "brand_story"})
    narrator = CastMember(name="narrator", age=40, on_screen=False, voice="calm", accent="neutral",
                          pace="slow", energy="low", speech_habits=["short sentences", "dry"])
    cast = look.model_copy(update={"cast": [*look.cast, narrator]})
    assert "told by a narrator" in "\n".join(storyboard_errors(board, story, cast))
    assert "at most one on-camera" in "\n".join(storyboard_errors(board, story, cast))
    assert storyboard_errors(voiceover_board(board), story, cast) == []
    on_screen_narrator = with_shot(voiceover_board(board), 0, character="narrator")
    assert "not an on-screen cast member" in "\n".join(storyboard_errors(on_screen_narrator, story, cast))


def test_ugc_selfie_shots_are_light_handheld(parts):
    board, brief, look = parts
    assert "light handheld" in "\n".join(storyboard_errors(with_shot(board, 0, camera_move="static"), brief, look))


def test_headlines_and_the_end_card_need_claim_checks_too(parts):
    board, brief, look = parts
    static = {**board.shots[2].model_dump(), "id": "s05", "route": "static", "duration_s": 0, "beats": [],
              "headline": "Up to 8 hours per charge"}
    with_static = Storyboard.model_validate({**board.model_dump(), "shots": [*board.model_dump()["shots"], static]})
    spoken = [LineCheck(shot_id=shot.id) for shot in board.shots if shot.dialogue_tts]

    def errors(extra):
        review = StoryboardReview(notes=[], line_checks=spoken + extra, storyboard=with_static)
        return "\n".join(review_errors(review, brief, look))

    assert "s05: line_checks has no entry" in errors([LineCheck(shot_id="end_card")])
    assert "end_card: line_checks has no entry" in errors([LineCheck(shot_id="s05")])
    unbacked = LineCheck(shot_id="s05", claims=[Claim(claim="up to 8 hours per charge")])
    assert "'up to 8 hours per charge' is not backed" in errors([unbacked, LineCheck(shot_id="end_card")])
    backed = LineCheck(shot_id="s05", claims=[Claim(claim="up to 8 hours per charge", fact=1)])
    assert errors([backed, LineCheck(shot_id="end_card")]) == ""


def test_critic_notes_must_be_clean_and_state_real_word_counts(parts):
    board, brief, look = parts
    checks = [LineCheck(shot_id=shot.id) for shot in board.shots if shot.dialogue_tts] + [LineCheck(shot_id="end_card")]

    def errors(issue, change):
        note = CriticNote(shot_id="s01", kind="other", issue=issue, change=change)
        review = StoryboardReview(notes=[note], line_checks=checks, storyboard=board)
        return "\n".join(review_errors(review, brief, look))

    assert errors("The hook was slow.", "Rewrote it to open on the tension.") == ""
    assert errors("The hook was slow.", "Rewrote the line (4 words).") == ""  # the real count is fine
    assert "final line has 4" in errors("The hook was slow.", "Rewrote the line (8 words).")
    rambling = "First I tried one line. Then it was rejected. So I wrote another."
    assert "plain sentences" in errors("The hook was slow.", rambling)
    second_thoughts = "The hook now reads 'Okay, nothing yet.' Wait, that adds a filler. So the line is 'Any second now.'"
    assert "plain sentences" in errors("The hook was slow.", second_thoughts)  # seen in a real critic reply


def test_new_cast_must_differ_from_personas_used_for_other_brands(parts):
    look = parts[2]
    used = [{"brand": "Noctave", "name": "dana", "age": 29, "look": "woman with shoulder-length dark wavy hair"}]
    problems = "\n".join(casting_errors(look, used))
    assert "age 28 is too close" in problems and "look is too close" in problems
    far = [{"brand": "Brasswick", "name": "arjun", "age": 46,
            "look": "broad-shouldered man with a grey beard, deep brown skin and a shaved head"}]
    assert casting_errors(look, far) == []
    assert "name is already used" in "\n".join(casting_errors(look, [{**far[0], "name": "maya"}]))


def test_real_personas_that_looked_alike_are_caught():
    meera = "Indian woman with medium-brown skin, slightly flushed cheeks, dark eyes, and shoulder-length black hair clipped up loosely"
    maya = "Woman with medium-brown skin, shoulder-length dark wavy hair pushed behind her ears, tired but friendly eyes"
    dana = "Woman with medium-brown skin, shoulder-length dark wavy hair loosely tied back, light freckles, no glasses"
    assert look_similarity(maya, dana) > 0.30 and look_similarity(meera, dana) > 0.30


def test_used_personas_come_from_samples_and_paid_runs_of_other_brands(done, tmp_path):
    run = done[0]
    for name, brand, paid in (("a", "Other", True), ("b", "Dewline", True), ("c", "DryRunBrand", False)):
        folder = tmp_path / "runs" / name
        folder.mkdir(parents=True)
        (folder / "brief.json").write_text('{"brand": "%s"}' % brand)
        (folder / "look.json").write_text(run.path("look.json").read_text("utf-8"), "utf-8")
        Ledger(folder / "ledger.jsonl").record("openrouter", "sonnet:look", 0.01, mock=not paid)
    found = used_personas("Dewline", tmp_path / "runs", samples_dir=tmp_path / "samples")
    assert [(p["brand"], p["name"]) for p in found] == [("Other", "maya")]  # not its own brand, not dry runs
