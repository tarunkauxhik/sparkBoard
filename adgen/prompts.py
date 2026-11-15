"""Turns a storyboard shot into model prompts. Prompts are compiled here, never hand-typed.

Each shot has two prompts:
- the keyframe prompt describes a still image (who, where, light);
- the motion prompt says only what moves and what is said. Veo starts from the
  keyframe (first-frame mode), so it does not need the scene described again.
"""
from adgen.schemas import Brief, Look, Shot

REALISM = {
    "ugc": "shot on a phone front camera, handheld, natural skin texture with pores, "
           "no makeup glow, slight noise",
    "default": "real lens look, one motivated light source, mixed color temperature, "
               "natural skin texture, off-center framing",
}
AVOID_IMAGE = "text, captions, logos drawn by the model, extra people, warped hands"
AVOID_VIDEO = "subtitles, on-screen text, music, extra people, warped hands"


def keyframe_prompt(shot: Shot, look: Look, brief: Brief) -> str:
    """Still image prompt. A cast member's look and outfit are repeated word for word
    in every shot, which is what keeps face, hair and clothes the same."""
    parts = [f"Camera: {shot.shot_type}, {shot.angle}, {shot.framing}."]
    if shot.character:
        who = next(member for member in look.cast if member.name == shot.character)
        parts.append(f"Subject: {who.look}, age {who.age}, wearing {who.outfit} "
                     f"(identity from reference). Expression: {shot.expression}.")
    parts.append(f"Moment: {shot.first_frame}.")
    if shot.product_visible:
        parts.append(f"Product: {brief.product} exactly as in the product reference.")
    parts.append(f"Setting: {look.setting.value} ({shot.location}).")
    parts.append(f"Lighting: {shot.lighting}.")
    parts.append(f"Style: {REALISM.get(brief.format, REALISM['default'])}.")
    parts.append(f"Avoid: {AVOID_IMAGE}.")
    return " ".join(parts)


def motion_prompt(shot: Shot) -> str:
    """Video prompt for a clip that starts from the shot's keyframe."""
    parts = [f"Camera: {shot.camera_move or 'static'}.", f"Action: {shot.action}."]
    if shot.route == "veo_talk":
        parts.append(f'Dialogue: {shot.speaker} says, in {shot.dialogue_lang}: "{shot.dialogue_tts}"')
    else:  # b-roll, and routes whose voice is added later from TTS
        parts.append("No one speaks, mouths stay closed.")
    parts.append(f"Audio: {shot.audio_notes}.")
    parts.append(f"Avoid: {AVOID_VIDEO}.")
    return " ".join(parts)
