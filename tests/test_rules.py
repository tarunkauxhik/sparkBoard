"""Storyboard and cast rules that are checked in code."""
import pytest

from adgen.qa import ClipScores, word_error_rate, words_pass
from adgen.rules import look_errors, review_errors, storyboard_errors
from adgen.schemas import (
    Brief, CastMember, Claim, LineCheck, Look, Shot, Storyboard, StoryboardReview, max_words,
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
    ({"duration_s": 5}, "4, 6 or 8"),
    ({"dialogue_caption": "word " * 16}, "too long for one shot"),
    ({"dialogue_caption": "सुबह से thakaan"}, "Roman script"),
    ({"dialogue_caption": "[sighs] so tired"}, "no audio tags"),
    ({"dialogue_tts": "[sighs] so [laughs] tired"}, "one audio tag"),
    ({"dialogue_lang": ""}, "dialogue_lang"),
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


def test_code_stretches_a_shot_to_fit_its_line(parts):
    shot = Shot.model_validate(changed_shot(parts[0], 0, dialogue_caption="Watch my face when I put this on."))
    assert shot.duration_s == 6  # 8 words do not fit the 4 s the writer asked for


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
    (1, {"dialogue_caption": "I love it so much!"}, "exclamation"),
    (1, {"first_frame": "her kid stands next to her"}, "no children"),
    (1, {"lighting": "a ring light in front of her"}, "ring light"),
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
    look = parts[2]
    assert look_errors(look) == []
    glossy = look.model_copy(update={"lens": look.lens.model_copy(update={"value": "8K cinematic lens"})})
    assert "cinematic" in "\n".join(look_errors(glossy))


def test_every_claim_in_every_spoken_line_needs_a_backing_fact(parts):
    board, brief, look = parts
    spoken = [shot.id for shot in board.shots if shot.dialogue_tts]

    def errors(line_checks):
        review = StoryboardReview(notes=[], line_checks=line_checks, storyboard=board)
        return "\n".join(review_errors(review, brief, look))

    none = [LineCheck(shot_id=shot_id) for shot_id in spoken]
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
    good = ClipScores(hands=4, label=5, lip_sync=3, ai_look=4, hook_strength=3)
    assert not good.needs_reroll()
    assert good.model_copy(update={"hands": 2}).needs_reroll()
