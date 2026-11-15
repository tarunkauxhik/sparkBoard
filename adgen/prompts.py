"""Turns a storyboard shot into a plain, labelled prompt. Prompts are never hand-typed."""
from adgen.schemas import Brief, Look, Shot, Storyboard

REALISM = {
    "ugc": "shot on a phone front camera, handheld, natural skin texture with pores, "
           "no makeup glow, slight noise",
    "default": "real lens look, one motivated light source, mixed color temperature, "
               "natural skin texture, off-center framing",
}
AVOID = "subtitles, on-screen text, extra people, warped hands"


def shot_prompt(shot: Shot, board: Storyboard, look: Look, brief: Brief) -> str:
    """Fixed order: camera, subject, action, setting, lighting, dialogue, audio, style, avoid.

    A character's description and outfit are repeated word for word in every prompt,
    which is what keeps clothes and hair the same between shots.
    """
    parts = [f"Camera: {shot.shot_type}, {shot.angle}, {shot.framing}, {shot.camera_move}."]
    if shot.character:
        who = next(c for c in board.characters if c.name == shot.character)
        parts.append(
            f"Subject: {who.description}, wearing {who.outfit} (identity from reference). "
            f"Expression: {shot.expression}."
        )
    parts.append(f"Action: {shot.action}.")
    parts.append(f"Setting: {look.setting.value}.")
    parts.append(f"Lighting: {shot.lighting}.")
    if shot.route == "veo_talk":  # other routes get their voice from TTS, not the video model
        parts.append(f'Dialogue: {shot.speaker} says, in {brief.language}: "{shot.dialogue_tts}"')
    parts.append(f"Audio: {shot.audio_notes}.")
    parts.append(f"Style: {REALISM.get(brief.format, REALISM['default'])}.")
    parts.append(f"Avoid: {AVOID}.")
    return " ".join(parts)
