"""Turns storyboard data into model prompts. Prompts are compiled here, never hand-typed.

The rules behind the wording, with their sources, are in docs/PROMPTING.md.
- Nano Banana (images): narrative prose, a named role for every reference image,
  a named lens and one light source.
- Veo (video): plain prose in the order cinematography, subject, action (timed beats),
  context, style; then the dialogue line and the ambient noise.
A persona's words are identical in every prompt, which keeps face, hair and clothes the same.
"""
import re
from pathlib import Path

from adgen.schemas import ON_CAMERA, Brief, CastMember, Look, Refs, Shot

UGC_LOOK = ("smartphone front camera, handheld, natural window light, visible pores and "
            "skin texture, slight noise, unretouched")
CLEAN_FRAME = "The frame is clean, without captions, on-screen text or graphics"
# Image models fill shelves with real-looking brands (a sample keyframe showed a tube close to a
# real toothpaste brand). Everything that is not the advertised product gets a blank label.
BLANK_PRODUCTS = ("Every other bottle, tube, box or pack in the scene is unbranded, with a plain blank "
                  "label and no readable words, logos or brand names")
AUDIO_TAG = re.compile(r"\s*\[[^\]]*\]\s*")  # ElevenLabs tags like [sighs]; Veo must not read them aloud


# Veo's speech came out with room echo in the smoke test; this asks for a close, dry voice.
DRY_VOICE = "Recorded close to the phone mic, dry intimate voice, small furnished room, no echo or reverb."


def _style(look: Look, brief: Brief, shot: Shot) -> str:
    if brief.format == "ugc":
        return UGC_LOOK
    # The brand colour is only named where the product is on screen, so it cannot leak into other shots.
    accent = f", {look.brand_accent.rstrip('.')}" if shot.product_visible and look.brand_accent else ""
    return f"{look.palette.value.rstrip('.')}{accent}, natural skin texture, real materials, unretouched"


def _sentence(text: str) -> str:
    """Text as one sentence: capital first letter, one full stop."""
    text = text.strip().rstrip(".")
    return text[:1].upper() + text[1:] + "."


def _member(look: Look, name: str) -> CastMember:
    return next(member for member in look.cast if member.name == name)


def character_sheet_prompt(member: CastMember) -> str:
    """Made once per persona, then passed as image 1 in every shot with that person."""
    return (
        "Create a character reference sheet of one person on a plain light grey background, "
        "four views side by side: front face close-up, three-quarter view, side profile and "
        f"full body. The person is {member.persona}. Soft even daylight from a window, relaxed "
        "neutral face, 50 mm lens at f/4, natural skin texture with visible pores, unretouched. "
        "The sheet is clean, without labels or text."
    )


def packshot_prompt(brief: Brief) -> str:
    """The clean product photo. The label text is spelled out in full, because an image
    model left to itself invents ingredients and sizes that are not product facts."""
    lines = [brief.brand] if brief.product.startswith(brief.brand) else [brief.brand, brief.product]
    label = " and ".join(f'"{line}"' for line in lines)
    return (
        f"Create a product photo of {brief.product} by {brief.brand}: the product alone, upright "
        "in the centre of a plain off-white background, its label facing the camera. "
        f"The label carries exactly this text and nothing else: {label}. No ingredients, "
        "no sizes, no other words or numbers anywhere on the product. "
        "Soft daylight from the left, 85 mm lens at f/8, true-to-life colors and materials."
    )


def location_prompt(look: Look, brief: Brief) -> str:
    return (
        f"Create a photo of an empty location with nobody in it: {look.setting.value.rstrip('.')}. "
        f"Light: {look.light.value.rstrip('.')}. Eye-level view, natural perspective. Vertical 9:16. "
        f"{BLANK_PRODUCTS}. {CLEAN_FRAME}."
    )


def keyframe_request(shot: Shot, look: Look, brief: Brief, refs: Refs) -> tuple[str, list[Path | str]]:
    """The still-image prompt for a shot and its reference images, in the order the prompt names them."""
    images, roles = [], []

    def use(path: str, role: str) -> None:
        images.append(path)
        roles.append(f"image {len(images)} is {role}")

    who = _member(look, shot.character) if shot.character else None
    if who and shot.face_visible:  # hands-only shots do not need the face sheet
        use(refs.characters[who.name], f"the character sheet of {who.name}: keep the face, hair and outfit exactly")
    if shot.product_visible:
        for path in refs.product:
            if brief.app_screen:
                use(path, f"the {brief.product} screen: show it on the phone display with the same "
                          "layout, words and colours")
            else:
                use(path, f"the product, {brief.product}: keep its shape, color and label exactly")
    if refs.location:
        use(refs.location, "the location: keep the room, its objects and its light")

    parts = ["Create a photorealistic still frame for a vertical 9:16 video.",
             "Use the reference images like this: " + "; ".join(roles) + ".",
             f"The moment: {shot.first_frame.rstrip('.')}."]
    if who:
        parts.append(f"Person{'' if shot.face_visible else ' (face out of frame)'}: {who.persona}.")
    parts += [
        f"Framing: {shot.shot_type}, {shot.angle}, {shot.framing.rstrip('.')}.",
        f"Setting: {shot.setting.rstrip('.')}.",
        f"Lens: {shot.lens.rstrip('.')}. Light: {shot.lighting.rstrip('.')}.",
        f"Look: {_style(look, brief, shot)}.",
        f"{BLANK_PRODUCTS}.",
        CLEAN_FRAME + ((", apart from the app screen on the phone." if brief.app_screen else
                        ", apart from the product's own label.") if shot.product_visible else "."),
    ]
    if shot.blank_label_text:  # dates and prices are printed by code later, never by the image model
        parts.append("One label area on the product is left blank and plain, with nothing printed on it.")
    return " ".join(parts), images


def avatar_prompt(shot: Shot) -> str:
    """Kling Avatar prompt: expression and movement only. The words come from the audio file."""
    beats = " ".join(_sentence(beat.action + (f", {beat.eye_line}" if beat.eye_line else "")) for beat in shot.beats)
    return (f"{shot.speaker.capitalize()} speaks the line naturally, {shot.delivery.rstrip('.')}. {beats} "
            f"Small natural head and shoulder movement, {shot.camera_move or 'static'} camera.")


def _stamp(seconds: float) -> str:
    return f"00:{round(seconds):02d}"


def motion_prompt(shot: Shot, look: Look, brief: Brief) -> str:
    """The video prompt for a clip that starts from the shot's keyframe (Veo first-frame mode)."""
    who = _member(look, shot.character) if shot.character else None
    parts = [_sentence(f"{shot.shot_type}, {shot.angle}, {shot.camera_move or 'static'} camera")]  # cinematography
    if who:                                                                             # subject
        to_lens = any("lens" in beat.eye_line or "camera" in beat.eye_line for beat in shot.beats)
        facing = ", turned toward the camera" if shot.route in ON_CAMERA and to_lens else ""
        parts.append(f"{who.name.capitalize()}, {who.persona}, the same person as in the reference image{facing}.")
    for beat in shot.beats:                                                             # action
        eyes = f", {beat.eye_line.rstrip('.')}" if beat.eye_line else ""
        parts.append(f"[{_stamp(beat.start_s)}-{_stamp(beat.end_s)}] {_sentence(beat.action + eyes)}")
    parts += [_sentence(shot.setting), _sentence(shot.lighting)]                       # context
    parts.append(_sentence(_style(look, brief, shot)))                                  # style
    if shot.route == "veo_talk":
        speaker = _member(look, shot.speaker)
        line = AUDIO_TAG.sub(" ", shot.dialogue_tts).strip()
        parts.append(f'{speaker.name.capitalize()} says, in {shot.dialogue_lang}, {speaker.accent}: "{line}"')
        parts.append(f"The delivery is {shot.delivery.rstrip('.')}.")
        # No "Ambient noise" line on speaking shots: naming a room tone made the voice echo.
        parts += [DRY_VOICE, "Clean frame without captions or on-screen text, no background music."]
    else:  # b-roll, and routes whose voice is added later from TTS
        parts += ["The scene plays without speech.", f"Ambient noise: {shot.audio_notes.rstrip('.')}.",
                  "Clean frame without captions or on-screen text, no background music, only room tone."]
    return " ".join(parts)
