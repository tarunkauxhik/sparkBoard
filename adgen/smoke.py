"""Smoke test: the fewest paid calls that answer the open questions, one step at a time.

Each step keeps its outputs in one folder (runs/smoke-<date>/): the media, a tasks/ folder
with every prompt, task ID, credit balance and cost, and the cost ledger.
A step that already has its output file skips that task, so steps can be run again safely.
"""
import json
import os
import subprocess
from pathlib import Path

import httpx
from PIL import Image

from adgen.editor import stream_seconds
from adgen.prompts import (
    AUDIO_TAG, avatar_prompt, character_sheet_prompt, keyframe_request, motion_prompt, packshot_prompt,
)
from adgen.providers.elevenlabs import ElevenLabs, ElevenLabsError
from adgen.providers.kie import (
    ASSUMED_AVATAR_USD_PER_S, ASSUMED_IMAGE_USD, ASSUMED_VEO_CLIP_USD, USD_PER_CREDIT, Kie,
    kling_avatar_payload, nano_banana_payload, veo_payload,
)
from adgen.providers.openrouter import OpenRouter
from adgen.qa import ClipScores, FaceCheck, word_error_rate
from adgen.schemas import Brief, Look, Refs, Shot, Storyboard

SAMPLES = Path("samples")  # the reviewed storyboards the smoke test draws from


def _sample(name: str) -> tuple[Brief, Look, Storyboard]:
    folder = SAMPLES / name
    return (Brief.model_validate_json((folder / "brief.json").read_text("utf-8")),
            Look.model_validate_json((folder / "look.json").read_text("utf-8")),
            Storyboard.model_validate_json((folder / "storyboard.json").read_text("utf-8")))


def _report(log: dict, name: str) -> None:
    print(f"done  {name}: {log['credits_used']:g} credits = ${log['cost_usd']:.3f} "
          f"(Kie reports creditsConsumed {log['credits_consumed']}; balance {log['credits_before']:g} -> "
          f"{log['credits_after']:g})")


def _image(kie: Kie, out: Path, prompt: str, reference_urls: list[str], aspect_ratio: str) -> None:
    if out.exists():
        print(f"have  {out.name}")
        return
    _report(kie.run_task(out.stem, nano_banana_payload(prompt, reference_urls, aspect_ratio),
                         ASSUMED_IMAGE_USD, out), out.name)


def step_a(kie: Kie, voice: ElevenLabs, eyes: OpenRouter, folder: Path) -> None:
    """Free checks: Kie balance, one upload, ElevenLabs usage."""
    credits = kie.credits()
    print(f"Kie balance: {credits:g} credits (about ${credits * USD_PER_CREDIT:.2f} at ${USD_PER_CREDIT}/credit)")

    probe = folder / "upload_probe.png"
    Image.new("RGB", (64, 64), "#6b8f76").save(probe)
    url = kie.upload(probe)
    reachable = httpx.get(url, timeout=60).status_code
    print(f"Kie upload: OK, host {httpx.URL(url).host}, file reachable: HTTP {reachable}")

    used = voice.credits_used()
    print(f"ElevenLabs credits used in the last 30 days: {used}")
    (folder / "step_a.json").write_text(json.dumps(
        {"kie_credits": credits, "upload_host": httpx.URL(url).host, "upload_reachable": reachable,
         "elevenlabs_credits_used_30d": used}, indent=1), "utf-8")


def step_b(kie: Kie, voice: ElevenLabs, eyes: OpenRouter, folder: Path) -> None:
    """Three images: meera's character sheet, the product packshot, and the keyframe of shot 1."""
    brief, look, board = _sample("skincare")
    shot = board.shots[0]
    who = next(member for member in look.cast if member.name == shot.character)

    sheet, packshot, keyframe = (folder / f"sheet_{who.name}.png", folder / "packshot.png",
                                 folder / f"keyframe_{shot.id}.png")
    _image(kie, sheet, character_sheet_prompt(who), [], "16:9")
    _image(kie, packshot, packshot_prompt(brief), [], "1:1")
    # The keyframe prompt names its reference images in order, so they are uploaded in that order.
    prompt, references = keyframe_request(shot, look, brief,
                                          Refs(characters={who.name: str(sheet)}, product=[str(packshot)]))
    if not keyframe.exists():
        urls = [kie.upload(Path(reference)) for reference in references]
        _image(kie, keyframe, prompt, urls, "9:16")


def step_c(kie: Kie, voice: ElevenLabs, eyes: OpenRouter, folder: Path) -> None:
    """One Veo Fast clip in English: skincare shot 1, starting from its keyframe."""
    brief, look, board = _sample("skincare")
    shot = board.shots[0]
    keyframe, clip = folder / f"keyframe_{shot.id}.png", folder / f"clip_{shot.id}_take1.mp4"
    if clip.exists():
        print(f"have  {clip.name}")
        return
    payload = veo_payload(motion_prompt(shot, look, brief), kie.upload(keyframe), "veo3_fast", shot.duration_s)
    _report(kie.run_task(clip.stem, payload, ASSUMED_VEO_CLIP_USD, clip), clip.name)


def step_d(kie: Kie, voice: ElevenLabs, eyes: OpenRouter, folder: Path) -> None:
    """One Veo Fast clip in Hinglish: fintech shot 1. Needs neha's character sheet and
    the shot's keyframe first (two images, counted in this step's cost)."""
    brief, look, board = _sample("fintech")
    shot = board.shots[0]
    who = next(member for member in look.cast if member.name == shot.character)
    sheet, keyframe, clip = (folder / f"sheet_{who.name}.png", folder / f"keyframe_fintech_{shot.id}.png",
                             folder / f"clip_fintech_{shot.id}_take1.mp4")
    _image(kie, sheet, character_sheet_prompt(who), [], "16:9")
    # No product reference: the product is an app, and its screen is not readable in this shot.
    prompt, references = keyframe_request(shot, look, brief, Refs(characters={who.name: str(sheet)}))
    if not keyframe.exists():
        _image(kie, keyframe, prompt, [kie.upload(Path(reference)) for reference in references], "9:16")
    if clip.exists():
        print(f"have  {clip.name}")
        return
    payload = veo_payload(motion_prompt(shot, look, brief), kie.upload(keyframe), "veo3_fast", shot.duration_s)
    _report(kie.run_task(clip.stem, payload, ASSUMED_VEO_CLIP_USD, clip), clip.name)


def _transcript(voice: ElevenLabs, audio: Path) -> dict:
    """Scribe transcript of an audio file, kept next to it so it is only paid for once."""
    saved = audio.with_suffix(".transcript.json")
    if not saved.exists():
        result = voice.transcribe(audio, stream_seconds(audio, "a:0"))
        saved.write_text(json.dumps(result, ensure_ascii=False, indent=1), "utf-8")
    return json.loads(saved.read_text("utf-8"))


def _heard(shot: Shot, transcript: dict) -> dict:
    """How a transcript compares with the script. Scribe may write Hindi in Devanagari or in
    Roman letters, so the line is compared in both forms and the better match counts."""
    words = transcript["words"]  # spoken words only: sound tags like [tongue clicking] are left out
    spoken = " ".join(word["word"] for word in words)
    rate = word_error_rate(shot.dialogue_caption, spoken, AUDIO_TAG.sub(" ", shot.dialogue_tts))
    return {"heard": transcript["text"], "language": transcript["language_code"],
            "word_error_rate": round(rate, 2),
            "speech_s": [words[0]["start_s"], words[-1]["end_s"]] if words else None}


def step_e(kie: Kie, voice: ElevenLabs, eyes: OpenRouter, folder: Path) -> None:
    """ElevenLabs: what was really said in both Veo clips, the voice changer on both,
    and TTS v3 against v4 with a library voice and the existing cloned voice."""
    library, clone = os.environ["ELEVENLABS_VOICE_LIBRARY"], os.environ["ELEVENLABS_VOICE_CLONE"]
    before, results = voice.credits_used(), {}

    for sample, name in (("skincare", "clip_s01_take1"), ("fintech", "clip_fintech_s01_take1")):
        shot = _sample(sample)[2].shots[0]
        video, audio, changed = folder / f"{name}.mp4", folder / f"{name}.wav", folder / f"{name}_voice.mp3"
        if not audio.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vn", "-ac", "1", str(audio)], check=True)
        results[name] = {"script": shot.dialogue_caption, **_heard(shot, _transcript(voice, audio))}
        if not changed.exists():
            voice.voice_change(audio, changed, library, stream_seconds(audio, "a:0"))
        results[changed.stem] = {"script": shot.dialogue_caption, **_heard(shot, _transcript(voice, changed))}
        muxed = folder / f"{name}_voice.mp4"  # the swapped voice back on the picture, to judge lip-sync
        if not muxed.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-i", str(changed), "-map", "0:v",
                            "-map", "1:a", "-c:v", "copy", "-c:a", "aac", str(muxed)], check=True)

    line = _sample("fintech")[2].shots[-1]  # a mixed-script Hinglish line
    for voice_name, voice_id in (("library", library), ("clone", clone)):
        for model in ("eleven_v3", "eleven_v4"):
            out = folder / f"tts_{voice_name}_{model}.mp3"
            try:
                if not out.exists():
                    voice.speak(line.dialogue_tts, out, voice_id, model)
                results[out.stem] = {"script": line.dialogue_caption, **_heard(line, _transcript(voice, out))}
            except ElevenLabsError as error:  # e.g. the key may not be allowed to use TTS
                results[out.stem] = {"error": str(error)[:200]}

    after = voice.credits_used()
    account = {product: after[product] - before.get(product, 0) for product in after
               if after[product] != before.get(product, 0)}
    (folder / "step_e.json").write_text(json.dumps(
        {"results": results, "account_credits_used_during_step": account}, ensure_ascii=False, indent=1), "utf-8")
    for name, result in results.items():
        print(name, json.dumps(result, ensure_ascii=False))
    print("Account credits used during this step (the account is shared):", account)


def step_f(kie: Kie, voice: ElevenLabs, eyes: OpenRouter, folder: Path) -> None:
    """Kling Avatar, the backup route: neha's keyframe speaks the Hinglish TTS line from step E."""
    shot = _sample("fintech")[2].shots[-1]
    image, audio = folder / "keyframe_fintech_s01.png", folder / "tts_library_eleven_v4.mp3"
    clip = folder / f"clip_avatar_fintech_{shot.id}_take1.mp4"
    if not clip.exists():
        payload = kling_avatar_payload(avatar_prompt(shot), kie.upload(image), kie.upload(audio))
        seconds = stream_seconds(audio, "a:0")
        _report(kie.run_task(clip.stem, payload, ASSUMED_AVATAR_USD_PER_S * seconds, clip), clip.name)
    print(f"audio in: {stream_seconds(audio, 'a:0'):.2f} s; clip out: video {stream_seconds(clip, 'v:0'):.2f} s, "
          f"audio {stream_seconds(clip, 'a:0'):.2f} s")


FACE_QUESTION = (
    "Image 1 is a character reference sheet of one person. Image 2 is a frame from an ad. "
    "Is the person in image 2 the same person as on the sheet? Compare face shape, eyes, nose, mouth, "
    "skin tone, hair and marks. Ignore pose, light, expression and clothes. "
    "score: 5 = clearly the same person, 3 = similar with visible differences, 1 = a different person.")
CLIP_QUESTION = (
    "This is one AI-generated clip for a short social video ad. Judge it as a strict reviewer who has "
    "seen many AI videos. The person should say: \"{line}\". Score each from 1 (unusable) to 5 (looks real): "
    "hands (fingers and grip stay natural), label (the product and its label stay the same and are not "
    "garbled), lip_sync (the mouth matches the words), ai_look (5 = no glossy, waxy or over-smooth look), "
    "hook_strength (would the first 2 seconds stop a scroll). In notes, list every concrete problem you see "
    "with its time in seconds, including objects that appear, vanish or change.")


def _small_image(source: Path, folder: Path) -> Path:
    out = folder / "review" / f"{source.stem}.jpg"
    out.parent.mkdir(exist_ok=True)
    if not out.exists():
        image = Image.open(source).convert("RGB")
        image.thumbnail((1024, 1024))
        image.save(out, quality=88)
    return out


def _frame(clip: Path, second: float, folder: Path) -> Path:
    out = folder / "review" / f"{clip.stem}_at_{second:g}s.png"
    out.parent.mkdir(exist_ok=True)
    if not out.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(second), "-i", str(clip),
                        "-frames:v", "1", str(out)], check=True)
    return out


def step_g(kie: Kie, voice: ElevenLabs, eyes: OpenRouter, folder: Path) -> None:
    """Gemini review: face checks against the character sheets (with one wrong pairing as a
    control) and the clip rubric on both Veo clips."""
    results = {}
    pairs = [("meera_keyframe", "sheet_meera.png", folder / "keyframe_s01.png"),
             ("meera_clip_frame", "sheet_meera.png", _frame(folder / "clip_s01_take1.mp4", 3, folder)),
             ("neha_keyframe", "sheet_neha.png", folder / "keyframe_fintech_s01.png"),
             ("control_meera_sheet_vs_neha", "sheet_meera.png", folder / "keyframe_fintech_s01.png")]
    for name, sheet, frame in pairs:
        check = eyes.look_at(f"face_{name}", FACE_QUESTION, FaceCheck,
                             images=[_small_image(folder / sheet, folder), _small_image(frame, folder)])
        results[f"face_{name}"] = check.model_dump()

    for sample, name in (("skincare", "clip_s01_take1"), ("fintech", "clip_fintech_s01_take1")):
        shot = _sample(sample)[2].shots[0]
        small = folder / "review" / f"{name}_480p.mp4"
        if not small.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(folder / f"{name}.mp4"),
                            "-vf", "scale=-2:480", "-c:a", "aac", str(small)], check=True)
        scores = eyes.look_at(f"rubric_{name}", CLIP_QUESTION.format(line=shot.dialogue_caption), ClipScores,
                              video=small, video_seconds=stream_seconds(small, "v:0"))
        results[f"rubric_{name}"] = {**scores.model_dump(), "needs_reroll": scores.needs_reroll()}

    (folder / "step_g.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), "utf-8")
    for name, result in results.items():
        print(name, json.dumps(result, ensure_ascii=False))


STEPS = {"a": step_a, "b": step_b, "c": step_c, "d": step_d, "e": step_e, "f": step_f, "g": step_g}
