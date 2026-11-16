"""Storyboard rules that need the brief and the cast. Checked in code, not left to the LLM.

Single-shot rules (durations, word counts, script, beats) live on the Shot model in schemas.py.
The source of each rule is listed in docs/PROMPTING.md.
"""
import re

from adgen.schemas import ON_CAMERA, SPOKEN, Brief, Look, Storyboard, StoryboardReview

LENGTH_TOLERANCE_S = 2
HOOK_MAX_WORDS = 8  # a hook line this short gets to the point in the first seconds
PRODUCT_AD_FORMATS = ("ugc", "product_hero")       # the product must be on screen in shot 1
VOICEOVER_FORMATS = ("brand_story", "product_hero")  # voiceover over b-roll, at most one on-camera line
WARM_UP_WORDS = ("okay", "ok", "so", "hey", "hi", "hello", "well", "alright", "guys", "listen", "um", "uh")
OVERUSED_PHRASES = [
    "game changer", "game-changer", "i was skeptical", "i was sceptical", "hey guys", "holy grail",
    "obsessed", "life changing", "life-changing", "trust me", "you won't believe", "hear me out",
]
GLOSSY_WORDS = ("8k", "4k", "cinematic", "flawless", "masterpiece", "ultra-detailed", "ring light")
MINORS = re.compile(r"\b(child|children|kid|kids|baby|toddler|teen|teens|teenager|schoolgirl|schoolboy)\b",
                    re.IGNORECASE)
SECOND_LIGHT = re.compile(r"\b(fill|plus|mixed|second|two|both)\b| and | \+ ", re.IGNORECASE)
BRANDS = re.compile(r"\b(iphone|samsung|galaxy|pixel|oneplus|xiaomi|huawei|sony|canon|nikon|fuji|fujifilm|"
                    r"leica|arri|gopro|zeiss|sigma|panasonic|lumix|dji|blackmagic|aputure|laowa|godox|nanlite)\b", re.IGNORECASE)
# Fast hand-on-object hits come out warped or with objects vanishing ("bangle" is not a hit).
IMPACTS = re.compile(r"\b(bang|slamm?|smash|pound|thump|whack|strike?|hitt?|punch|smack)(s|es|ed|ing)?\b",
                     re.IGNORECASE)
WORD_COUNT_CLAIM = re.compile(r"(\d+)[ -]words?\b")
NOTE_MAX_SENTENCES = 2


def storyboard_errors(board: Storyboard, brief: Brief, look: Look) -> list[str]:
    """Rule breaks in a storyboard. An empty list means it passes."""
    errors = []
    on_screen = {member.name for member in look.cast if member.on_screen}
    voices = {member.name for member in look.cast}
    for shot in board.shots:
        if shot.character and shot.character not in on_screen:
            errors.append(f"{shot.id}: character {shot.character!r} is not an on-screen cast member {sorted(on_screen)}")
        if shot.speaker and shot.speaker not in voices:
            errors.append(f"{shot.id}: speaker {shot.speaker!r} is not in the cast {sorted(voices)}")
        line = shot.dialogue_caption.lower()
        for phrase in OVERUSED_PHRASES:
            if phrase in line:
                errors.append(f"{shot.id}: overused phrase {phrase!r}, say it another way")
        seen = " ".join([shot.first_frame, shot.framing, shot.setting, shot.lens, shot.lighting,
                         *(beat.action for beat in shot.beats)])
        if MINORS.search(seen):
            errors.append(f"{shot.id}: no children on screen, adults only")
        for word in GLOSSY_WORDS:
            if word in seen.lower():
                errors.append(f"{shot.id}: remove {word!r}; describe a real lens and one real light source")
        if shot.route == "avatar_talk":
            errors.append(f"{shot.id}: avatar_talk is a fallback that code may switch to; write veo_talk")
        hits = IMPACTS.search(" ".join(beat.action for beat in shot.beats))
        if hits:
            errors.append(f"{shot.id}: no fast hand-on-object impacts ({hits.group()!r}); "
                          "use a gentle tap, a point, or set the object down")
        if SECOND_LIGHT.search(shot.lighting):
            errors.append(f"{shot.id}: lighting must name one light source only, got {shot.lighting!r}")
        if BRANDS.search(seen):
            errors.append(f"{shot.id}: never name a real phone, camera or lens brand; "
                          "for phone shots write 'smartphone front camera, 24 mm equivalent'")
        if brief.format == "ugc" and shot.route in ON_CAMERA and shot.camera_move.lower() != "light handheld":
            errors.append(f"{shot.id}: selfie speaking shots in a ugc ad use camera_move 'light handheld'")

    used = {name for shot in board.shots for name in (shot.character, shot.speaker) if name}
    for member in look.cast:
        if member.name not in used:
            errors.append(f"cast member {member.name!r} appears in no shot: every cast member must be "
                          "seen or heard")

    low, high = brief.target_length_s - LENGTH_TOLERANCE_S, brief.target_length_s + LENGTH_TOLERANCE_S
    if not low <= board.length_s <= high:
        errors.append(f"shot durations add up to {board.length_s} s, but must be between {low} and "
                      f"{high} s: cut words (a shorter line gets a shorter shot) or drop a shot")

    hook = board.shots[0]
    hook_words = hook.dialogue_caption.lower().split()
    if len(hook_words) > HOOK_MAX_WORDS:
        errors.append(f"{hook.id}: the hook line has {len(hook_words)} words, the limit is {HOOK_MAX_WORDS}")
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
    if brief.format in VOICEOVER_FORMATS:
        if "vo_only" not in routes:
            errors.append(f"a {brief.format} ad is told by a narrator: use vo_only shots (voiceover over b-roll)")
        if sum(route in ON_CAMERA for route in routes) > 1:
            errors.append(f"a {brief.format} ad has at most one on-camera spoken line; the rest is voiceover")
    spoken = [shot for shot in board.shots if shot.route in SPOKEN]
    if spoken and spoken[-1].purpose != "cta":
        errors.append(f"{spoken[-1].id}: the last spoken shot must be the soft call to action (purpose 'cta')")

    if errors:  # the model miscounts, so every rejection carries the real numbers
        errors.append(f"Real counts, measured by code on dialogue_caption: {board.counts}")
    return errors


def look_errors(look: Look, brief: Brief) -> list[str]:
    """Rule breaks in the look: glossy 'AI look' words, or a narrator format without a narrator."""
    errors = [f"{name}: remove {word!r}; describe a real lens and one real light source"
              for name, choice in look.choices()
              for word in GLOSSY_WORDS if word in choice.value.lower()]
    errors += [f"{name}: never name a real phone, camera or lens brand; for a phone write "
               "'smartphone front camera, 24 mm equivalent'"
               for name, choice in look.choices() if BRANDS.search(choice.value)]
    if brief.format in VOICEOVER_FORMATS and all(member.on_screen for member in look.cast):
        errors.append(f"a {brief.format} ad is told in voiceover: add a narrator to the cast with on_screen false")
    return errors


def review_errors(review: StoryboardReview, brief: Brief, look: Look) -> list[str]:
    """Rule breaks in the critic's reply: its storyboard, its claim checks and its notes."""
    board = review.storyboard
    errors = storyboard_errors(board, brief, look)
    shots = {shot.id: shot for shot in board.shots}

    # Every text the viewer hears or reads needs a claim check: lines, headlines, the end card.
    checks = {check.shot_id: check for check in review.line_checks}
    texts = [shot.id for shot in board.shots if shot.route in SPOKEN or shot.route == "static"] + ["end_card"]
    for target in texts:
        check = checks.get(target)
        if check is None:
            errors.append(f"{target}: line_checks has no entry for this text")
            continue
        for claim in check.claims:
            if claim.fact is None or not 0 <= claim.fact < len(brief.product_facts):
                errors.append(f"{target}: the claim {claim.claim!r} is not backed by product_facts; "
                              "rewrite the text without it")
        if target == board.shots[0].id and check.claims:
            errors.append(f"{target}: the hook must not make product claims; open on the tension instead")

    # Notes: clean sentences, and any word count they state must be the real one.
    for note in review.notes:
        for text in (note.issue, note.change):
            if len(re.findall(r"[.?]['\"]?\s+[A-Z\"']", text)) >= NOTE_MAX_SENTENCES:
                errors.append(f"note on {note.shot_id}: keep issue and change to at most "
                              f"{NOTE_MAX_SENTENCES} plain sentences each, without drafts or history")
        shot = shots.get(note.shot_id)
        for stated in WORD_COUNT_CLAIM.findall(note.change):
            if shot and int(stated) != shot.words:
                errors.append(f"note on {note.shot_id} says {stated} words, but the final line has "
                              f"{shot.words}; leave word counts out of notes")
    return errors
