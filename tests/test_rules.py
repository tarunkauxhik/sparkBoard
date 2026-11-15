"""Storyboard and cast rules that are checked in code."""
import pytest

from adgen.rules import review_errors, storyboard_errors
from adgen.schemas import Brief, CastMember, LineCheck, Look, Shot, Storyboard, StoryboardReview, max_words


@pytest.fixture
def parts(done):
    run = done[0]
    return run.load("storyboard.json", Storyboard), run.load("brief.json", Brief), run.load("look.json", Look)


def changed_shot(board: Storyboard, index: int, **changes) -> dict:
    return {**board.shots[index].model_dump(), **changes}


def test_the_mock_storyboard_passes(parts):
    assert storyboard_errors(*parts) == []


def test_word_limits_leave_silence_at_both_ends():
    assert (max_words(4), max_words(6), max_words(8)) == (6, 11, 15)


@pytest.mark.parametrize("changes, message", [
    ({"duration_s": 5}, "4, 6 or 8"),
    ({"dialogue_caption": "word " * 16}, "too long for one shot"),
    ({"dialogue_caption": "सुबह से thakaan"}, "Roman script"),
    ({"dialogue_lang": ""}, "dialogue_lang"),
    ({"shot_type": "wide shot"}, "medium close-up"),
    ({"route": "veo_broll"}, "silent"),
])
def test_shot_rules(parts, changes, message):
    with pytest.raises(ValueError, match=message):
        Shot.model_validate(changed_shot(parts[0], 1, **changes))  # shot 2: a 6 s talking shot


def test_code_stretches_a_shot_to_fit_its_line(parts):
    shot = Shot.model_validate(changed_shot(parts[0], 0, dialogue_caption="Watch my face when I put this on."))
    assert shot.duration_s == 6  # 8 words do not fit the 4 s the writer asked for


def test_cast_must_be_adult_and_not_a_likeness():
    member = {"name": "maya", "age": 28, "look": "woman with dark hair", "outfit": "grey t-shirt", "voice": "warm"}
    CastMember.model_validate(member)
    with pytest.raises(ValueError, match="25 or older"):
        CastMember.model_validate({**member, "age": 19})
    with pytest.raises(ValueError, match="likeness"):
        CastMember.model_validate({**member, "look": "looks like a famous film star"})


@pytest.mark.parametrize("index, changes, message", [
    (1, {"speaker": "riya"}, "not in the cast"),
    (2, {"duration_s": 8}, "add up to"),  # 22 s against a target of 18 s
    (0, {"duration_s": 6, "dialogue_caption": "this hook line just keeps going on and on"}, "hook line"),
    (1, {"dialogue_caption": "honestly this is a game changer"}, "overused"),
    (1, {"action": "her kid runs into the room"}, "no children"),
])
def test_storyboard_rules(parts, index, changes, message):
    board, brief, look = parts
    shots = [shot.model_dump() for shot in board.shots]
    shots[index] = changed_shot(board, index, **changes)
    broken = Storyboard.model_validate({"title": board.title, "plan": board.plan, "shots": shots})
    assert message in "\n".join(storyboard_errors(broken, brief, look))


def test_product_must_show_by_shot_two(parts):
    board, brief, look = parts
    shots = [{**shot.model_dump(), "product_visible": False} for shot in board.shots]
    broken = Storyboard.model_validate({"title": board.title, "plan": board.plan, "shots": shots})
    assert "visible in shot 1 or 2" in "\n".join(storyboard_errors(broken, brief, look))


def test_ugc_needs_a_broll_shot(parts):
    board, brief, look = parts
    shots = [shot.model_dump() for shot in board.shots if shot.route != "veo_broll"]
    shots.append({**shots[-1], "id": "s05"})  # keep the length in range with a fourth talking shot
    talk_only = Storyboard.model_validate({"title": board.title, "plan": board.plan, "shots": shots})
    assert "veo_broll" in "\n".join(storyboard_errors(talk_only, brief, look))


def test_every_spoken_line_needs_a_claim_check_backed_by_a_product_fact(parts):
    board, brief, look = parts
    spoken = [shot.id for shot in board.shots if shot.dialogue_tts]

    def errors(line_checks):
        review = StoryboardReview(notes=[], line_checks=line_checks, storyboard=board)
        return "\n".join(review_errors(review, brief, look))

    backed = [LineCheck(shot_id=shot_id, claim="no fragrance", fact=0) for shot_id in spoken]
    assert errors(backed) == ""
    assert "no entry" in errors(backed[1:])
    invented = [LineCheck(shot_id=shot_id, claim="full refund") for shot_id in spoken]
    assert "not backed by product_facts" in errors(invented)
    assert "not backed by product_facts" in errors([LineCheck(shot_id=s, claim="x", fact=99) for s in spoken])
