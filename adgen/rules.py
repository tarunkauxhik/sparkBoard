"""Storyboard rules that need the brief and the cast. Checked in code, not left to the LLM.

Single-shot rules (durations, word rate, script) live on the Shot model in schemas.py.
"""
import re

from adgen.schemas import SPOKEN, Brief, Look, Storyboard

LENGTH_TOLERANCE_S = 2
HOOK_MAX_WORDS = 8  # a hook line this short gets to the point in the first seconds
PRODUCT_AD_FORMATS = ("ugc", "product_hero")  # the product must be on screen by shot 2
OVERUSED_HOOKS = [
    "game changer", "game-changer", "i was skeptical", "i was sceptical", "holy grail",
    "obsessed", "life changing", "life-changing", "trust me", "you won't believe", "hear me out",
]
MINORS = re.compile(r"\b(child|children|kid|kids|baby|toddler|teen|teens|teenager|schoolgirl|schoolboy)\b",
                    re.IGNORECASE)


def storyboard_errors(board: Storyboard, brief: Brief, look: Look) -> list[str]:
    """Rule breaks in a storyboard. An empty list means it passes."""
    errors = []
    cast = {member.name for member in look.cast}
    for shot in board.shots:
        for who in (shot.character, shot.speaker):
            if who and who not in cast:
                errors.append(f"{shot.id}: {who!r} is not in the cast {sorted(cast)}")
        line = shot.dialogue_caption.lower()
        for phrase in OVERUSED_HOOKS:
            if phrase in line:
                errors.append(f"{shot.id}: overused phrase {phrase!r}, say it another way")
        seen = " ".join([shot.first_frame, shot.action, shot.framing, shot.expression])
        if MINORS.search(seen):
            errors.append(f"{shot.id}: no children on screen, adults only")

    total = sum(shot.duration_s for shot in board.shots if shot.route != "static")
    if abs(total - brief.target_length_s) > LENGTH_TOLERANCE_S:
        errors.append(f"shot durations add up to {total} s, the target is "
                      f"{brief.target_length_s} s (within {LENGTH_TOLERANCE_S} s)")

    hook = board.shots[0]
    if hook.route in SPOKEN and len(hook.dialogue_caption.split()) > HOOK_MAX_WORDS:
        errors.append(f"{hook.id}: the hook line must be {HOOK_MAX_WORDS} words or fewer")
    if brief.format in PRODUCT_AD_FORMATS and not any(shot.product_visible for shot in board.shots[:2]):
        errors.append("the product must be visible in shot 1 or 2")
    return errors
