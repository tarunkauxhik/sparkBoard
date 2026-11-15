"""Storyboard rules that need the brief and the cast. Checked in code, not left to the LLM.

Single-shot rules (durations, word rate, script, beats) live on the Shot model in schemas.py.
The source of each rule is listed in docs/PROMPTING.md.
"""
import re

from adgen.schemas import SPOKEN, Brief, Look, Storyboard, StoryboardReview, max_words

LENGTH_TOLERANCE_S = 2
HOOK_MAX_WORDS = 8  # a hook line this short gets to the point in the first seconds
PRODUCT_AD_FORMATS = ("ugc", "product_hero")  # the product must be on screen in shot 1
WARM_UP_WORDS = ("okay", "ok", "so", "hey", "hi", "hello", "well", "alright", "guys", "listen", "um", "uh")
OVERUSED_PHRASES = [
    "game changer", "game-changer", "i was skeptical", "i was sceptical", "hey guys", "holy grail",
    "obsessed", "life changing", "life-changing", "trust me", "you won't believe", "hear me out",
]
GLOSSY_WORDS = ("8k", "4k", "cinematic", "flawless", "masterpiece", "ultra-detailed", "ring light")
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
        for phrase in OVERUSED_PHRASES:
            if phrase in line:
                errors.append(f"{shot.id}: overused phrase {phrase!r}, say it another way")
        if "!" in line:
            errors.append(f"{shot.id}: no exclamation marks, they read as forced enthusiasm")
        seen = " ".join([shot.first_frame, shot.framing, shot.lighting, *(beat.action for beat in shot.beats)])
        if MINORS.search(seen):
            errors.append(f"{shot.id}: no children on screen, adults only")
        for word in GLOSSY_WORDS:
            if word in seen.lower():
                errors.append(f"{shot.id}: remove {word!r}; describe a real lens and one real light source")

    total = sum(shot.duration_s for shot in board.shots if shot.route != "static")
    if abs(total - brief.target_length_s) > LENGTH_TOLERANCE_S:
        # Spell out the real numbers: the model cannot be trusted to count them itself.
        detail = ", ".join(
            f"{shot.id} {shot.duration_s} s" + (f" ({len(shot.dialogue_caption.split())} words)"
                                                if shot.route in SPOKEN else "")
            for shot in board.shots if shot.route != "static")
        errors.append(
            f"shot durations add up to {total} s, but must be between "
            f"{brief.target_length_s - LENGTH_TOLERANCE_S} and {brief.target_length_s + LENGTH_TOLERANCE_S} s. "
            f"Now: {detail}. A spoken line of up to {max_words(4)} words takes 4 s, up to "
            f"{max_words(6)} takes 6 s, up to {max_words(8)} takes 8 s: cut words or drop a shot.")

    hook = board.shots[0]
    hook_words = hook.dialogue_caption.lower().split()
    if len(hook_words) > HOOK_MAX_WORDS:
        errors.append(f"{hook.id}: the hook line must be {HOOK_MAX_WORDS} words or fewer")
    if hook_words and hook_words[0].strip(",.…-") in WARM_UP_WORDS:
        errors.append(f"{hook.id}: the hook opens with the warm-up word {hook_words[0]!r}; "
                      "start on the tension itself")

    routes = [shot.route for shot in board.shots]
    if brief.format in PRODUCT_AD_FORMATS and not hook.product_visible:
        errors.append("the product must be visible in shot 1")
    if brief.format == "ugc" and "veo_broll" not in routes:
        errors.append("a ugc ad needs at least one silent veo_broll shot (product, hands or texture)")
    if brief.format == "product_hero" and "static" not in routes:
        errors.append("a product_hero ad needs at least one static shot with a headline")
    spoken = [shot for shot in board.shots if shot.route in SPOKEN]
    if spoken and spoken[-1].purpose != "cta":
        errors.append(f"{spoken[-1].id}: the last spoken shot must be the soft call to action (purpose 'cta')")
    return errors


def look_errors(look: Look) -> list[str]:
    """Rule breaks in the look: no glossy 'AI look' words in any choice."""
    return [f"{name}: remove {word!r}; describe a real lens and one real light source"
            for name, choice in look if name != "cast"
            for word in GLOSSY_WORDS if word in choice.value.lower()]


def review_errors(review: StoryboardReview, brief: Brief, look: Look) -> list[str]:
    """Rule breaks in the critic's reply: its storyboard, plus a claim check for every spoken line."""
    board = review.storyboard
    errors = storyboard_errors(board, brief, look)
    checks = {check.shot_id: check for check in review.line_checks}
    for shot in board.shots:
        if shot.route not in SPOKEN:
            continue
        check = checks.get(shot.id)
        if check is None:
            errors.append(f"{shot.id}: line_checks has no entry for this spoken shot")
            continue
        for claim in check.claims:
            if claim.fact is None or not 0 <= claim.fact < len(brief.product_facts):
                errors.append(f"{shot.id}: the claim {claim.claim!r} is not backed by product_facts; "
                              "rewrite the line without it")
        if shot is board.shots[0] and check.claims:
            errors.append(f"{shot.id}: the hook must not make product claims; open on the tension instead")
    return errors
