"""ffmpeg editor: checks an edit list, then renders it into the final 9:16 video.

How the render avoids audio drift:
- every cut is first normalized to the same size, frame rate and pixel format;
- each cut's length is a whole number of frames, and its sound is cut to that exact length;
- the sound is joined into one master track and muxed once (never `-shortest`).
"""
import re
import shutil
import subprocess
from pathlib import Path

from adgen.run import Run
from adgen.clicks import turn_down
from adgen.schemas import Audio, Check, Cut, EditList, EndCard
from adgen.statics import FONT, end_card

WIDTH, HEIGHT, FPS, SAMPLE_RATE = 1080, 1920, 24, 48000
MAX_AD_SECONDS = 60
TRIM_PAD_S = 0.4   # default time kept before the first word and after the last (--trim-pad)
END_CARD_S = 2.0
DUCK_LEVEL = 0.15  # a ducked click keeps 15% of its level (about -16 dB)
VO_BED_LEVEL = 0.3  # Veo's own sound under a narrator, about -10 dB
CAPTION_WORDS = 4      # max words per caption chunk
CAPTION_BOTTOM = 0.72  # captions end at 72% of the height, clear of faces and app buttons
NORMALIZE = (f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase:flags=lanczos,"
             f"crop={WIDTH}:{HEIGHT},fps={FPS},format=yuv420p,setsar=1")
LOUDNORM = "loudnorm=I=-14:TP=-1.5:LRA=11"
ENCODE = ["-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p"]
# Grain makes x264 files huge (100 MB for 24 s), so the final file is capped at a social-media bitrate.
BITRATE_CAP = ["-maxrate", "8M", "-bufsize", "16M"]
ASS_HEADER = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {WIDTH}
PlayResY: {HEIGHT}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Inter Variable,68,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,5,1,2,90,90,{round(HEIGHT * (1 - CAPTION_BOTTOM))},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ffmpeg(run: Run, *args) -> None:
    """Run ffmpeg inside the run folder, so every path is short and relative."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)], cwd=run.dir, check=True)


def stream_seconds(path: Path, stream: str) -> float:
    """Length of the video ("v:0") or audio ("a:0") stream. 0 if the file has no such stream."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries", "stream=duration",
         "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True).stdout.strip()
    return float(out) if out else 0.0


def _frames(cut: Cut) -> int:
    return round((cut.out_s - cut.in_s) * FPS)


def _exact_length(seconds: float) -> str:
    """Audio filters that pad or trim sound to an exact sample count.

    Counting samples (not timestamps) matters: AAC clips start a few milliseconds
    late, and cutting by time made every piece about 20 ms short.
    """
    samples = round(seconds * SAMPLE_RATE)
    return f"aresample={SAMPLE_RATE},asetpts=PTS-STARTPTS,apad,atrim=end_sample={samples}"


def grab_frame(clip: Path, second: float, out: Path) -> Path:
    """Save one frame of a clip as an image (used by the face check)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{second:.2f}", "-i", str(clip),
                    "-frames:v", "1", str(out)], check=True)
    return out


def build_edit_list(audio: Audio, durations: dict[str, float], end_card_line: str,
                    pad: float = TRIM_PAD_S) -> EditList:
    """Straight cuts in storyboard order. A spoken clip is trimmed to its words plus `pad`
    seconds, which also removes the warped or drifting frames Veo often ends a clip on."""
    cuts = []
    for clip in audio.clips:
        length = durations[clip.shot_id]
        if clip.words:
            start = max(0.0, clip.words[0].start_s - pad)
            end = min(length, clip.words[-1].end_s + pad)
            reason = f"trimmed to the spoken words plus {pad:g} s at each end"
        else:
            start, end, reason = 0.0, length, "silent shot, full take"
        cuts.append(Cut(shot_id=clip.shot_id, file=clip.file, in_s=round(start, 2), out_s=round(end, 2),
                        reason=reason))
    return EditList(cuts=cuts, end_card=EndCard(line=end_card_line, duration_s=END_CARD_S))


def clean_voice(video: Path, voice: Path, out: Path, clicks: list[tuple[float, float]] = ()) -> None:
    """Put an isolated voice back on its clip, with its stray clicks muted, over a very quiet
    room-tone bed (the isolator leaves dead silence between words, which sounds unnatural)."""
    muted = out.with_name(f"{out.stem}_voice_muted.wav")
    turn_down(voice, list(clicks), 0.0, muted)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(video), "-i", str(muted),
         "-f", "lavfi", "-i", f"anoisesrc=color=pink:amplitude=0.002:sample_rate={SAMPLE_RATE}",
         "-filter_complex", "[1:a][2:a]amix=inputs=2:duration=first:normalize=0[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-ar", str(SAMPLE_RATE), str(out)],
        check=True)
    muted.unlink()


def lay_voiceover(video: Path, voice: Path, out: Path, start_s: float) -> None:
    """Put a narrator's line over a silent b-roll clip: Veo's own sound stays as a low bed and
    the voice starts at `start_s`. The clip keeps its length."""
    seconds = stream_seconds(video, "v:0")
    delay = int(start_s * 1000)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(video), "-i", str(voice), "-filter_complex",
         f"[0:a]volume={VO_BED_LEVEL}[bed];[1:a]aresample={SAMPLE_RATE},adelay={delay}|{delay}[vo];"
         f"[bed][vo]amix=inputs=2:duration=first:normalize=0[a]",
         "-map", "0:v", "-map", "[a]", "-t", f"{seconds:.3f}", "-c:v", "copy", "-c:a", "aac",
         "-ar", str(SAMPLE_RATE), str(out)], check=True)


def duck_clicks(video: Path, out: Path, clicks: list[tuple[float, float]]) -> None:
    """Turn stray clicks down in a clip that keeps Veo's own audio. They are ducked, not muted,
    so the room tone does not drop out to silence."""
    ducked = out.with_name(f"{out.stem}_ducked.wav")
    turn_down(video, clicks, DUCK_LEVEL, ducked)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-i", str(ducked), "-map", "0:v", "-map", "1:a",
                    "-c:v", "copy", "-c:a", "aac", "-ar", str(SAMPLE_RATE), str(out)], check=True)
    ducked.unlink()


def final_checks(final: Path, end_card_s: float) -> list[Check]:
    """Code checks on the finished video: lengths, loudness, and black or silent gaps
    (measured before the end card, which is dark and silent on purpose)."""
    video, sound = stream_seconds(final, "v:0"), stream_seconds(final, "a:0")
    body = f"{video - end_card_s:.2f}"
    log = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-t", body, "-i", str(final),
         "-vf", "blackdetect=d=0.5", "-af", "silencedetect=n=-50dB:d=1.0,ebur128", "-f", "null", "-"],
        capture_output=True, text=True).stderr
    loudness = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", log)[-1])
    black, silent = len(re.findall("black_start", log)), len(re.findall("silence_start", log))
    return [
        Check(name="picture and sound are the same length", passed=abs(video - sound) < 0.1,
              detail=f"{abs(video - sound):.3f} s apart"),
        Check(name="loudness is -14 LUFS, give or take 1", passed=abs(loudness + 14) <= 1, detail=f"{loudness} LUFS"),
        Check(name="no black gaps", passed=black == 0, detail=f"{black} found"),
        Check(name="no silent gaps", passed=silent == 0, detail=f"{silent} found"),
    ]


def validate_edit_list(edit: EditList, audio: Audio, run: Run) -> list[str]:
    """Problems that must be fixed before rendering. An empty list means the edit is fine."""
    errors = []
    words = {clip.shot_id: clip.words for clip in audio.clips}
    for cut in edit.cuts:
        path = run.dir / cut.file
        if not path.exists():
            errors.append(f"{cut.shot_id}: file {cut.file} does not exist")
            continue
        if not 0 <= cut.in_s < cut.out_s <= stream_seconds(path, "v:0") + 0.05:
            errors.append(f"{cut.shot_id}: in/out {cut.in_s}-{cut.out_s} is outside the clip")
        for word in words.get(cut.shot_id, []):
            for point in (cut.in_s, cut.out_s):
                if word.start_s + 0.01 < point < word.end_s - 0.01:
                    errors.append(f"{cut.shot_id}: cut at {point} s lands inside the word {word.word!r}")
    total = sum(_frames(cut) for cut in edit.cuts) / FPS + edit.end_card.duration_s
    if total > MAX_AD_SECONDS:
        errors.append(f"the ad is {total:.1f} s, longer than {MAX_AD_SECONDS} s")
    return errors


def caption_events(edit: EditList, audio: Audio) -> list[tuple[float, float, str]]:
    """(start, end, text) on the final timeline: the spoken words in chunks of up to 4."""
    words = {clip.shot_id: clip.words for clip in audio.clips}
    events, cut_start = [], 0.0
    for cut in edit.cuts:
        heard = [w for w in words.get(cut.shot_id, [])
                 if w.start_s >= cut.in_s - 0.01 and w.end_s <= cut.out_s + 0.01]
        for i in range(0, len(heard), CAPTION_WORDS):
            chunk = heard[i:i + CAPTION_WORDS]
            events.append((cut_start + chunk[0].start_s - cut.in_s,
                           cut_start + chunk[-1].end_s - cut.in_s,
                           " ".join(w.word for w in chunk)))
        cut_start += _frames(cut) / FPS
    return events


def _ass_time(seconds: float) -> str:
    minutes, secs = divmod(seconds, 60)
    return f"0:{int(minutes):02d}:{secs:05.2f}"


def render_video(run: Run, edit: EditList, audio: Audio, brand: str, product: Path | None = None) -> str:
    """Render the edit list to final/ad_9x16.mp4 and return that path (relative to the run)."""
    run.path("work/x")  # creates work/, a temp folder deleted at the end
    speaking = {clip.shot_id for clip in audio.clips if clip.words}
    pictures, sounds = [], []

    # 1. Each cut becomes a normalized silent video piece and a sound piece of the same length.
    for i, cut in enumerate(edit.cuts):
        seconds = _frames(cut) / FPS
        _ffmpeg(run, "-ss", cut.in_s, "-i", cut.file, "-frames:v", _frames(cut),
                "-vf", NORMALIZE, "-an", *ENCODE, f"work/v{i:02d}.mp4")
        if stream_seconds(run.dir / cut.file, "a:0"):
            # Level speech per clip; leave quiet room tone alone, loudnorm would turn it into hiss.
            level = f"{LOUDNORM}," if cut.shot_id in speaking else ""
            _ffmpeg(run, "-ss", cut.in_s, "-i", cut.file, "-vn",
                    "-af", level + _exact_length(seconds), "-ac", 2, f"work/a{i:02d}.wav")
        else:
            _ffmpeg(run, "-f", "lavfi", "-i", f"anullsrc=r={SAMPLE_RATE}:cl=stereo",
                    "-t", seconds, f"work/a{i:02d}.wav")
        pictures.append(f"v{i:02d}.mp4")
        sounds.append(f"a{i:02d}.wav")

    # 2. End card, drawn in code. It has no sound piece: the master track is padded over it.
    end_card(brand, edit.end_card.line, run.path("work/end_card.png"), product)
    card_frames = round(edit.end_card.duration_s * FPS)
    _ffmpeg(run, "-loop", 1, "-i", "work/end_card.png", "-frames:v", card_frames,
            "-vf", NORMALIZE, "-an", *ENCODE, "work/end_card.mp4")
    pictures.append("end_card.mp4")
    total_seconds = (sum(_frames(cut) for cut in edit.cuts) + card_frames) / FPS

    # 3. Join the pieces: one picture track, one master sound track at -14 LUFS.
    run.path("work/pictures.txt").write_text("".join(f"file '{name}'\n" for name in pictures))
    run.path("work/sounds.txt").write_text("".join(f"file '{name}'\n" for name in sounds))
    _ffmpeg(run, "-f", "concat", "-i", "work/pictures.txt", "-c", "copy", "work/picture.mp4")
    _ffmpeg(run, "-f", "concat", "-i", "work/sounds.txt",
            "-af", f"{LOUDNORM},{_exact_length(total_seconds)}", "work/master.wav")

    # 4. Burn in captions, add light grain, and mux picture and sound once.
    lines = [f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Caption,,0,0,0,,{text}\n"
             for start, end, text in caption_events(edit, audio)]
    run.path("work/captions.ass").write_text(ASS_HEADER + "".join(lines), "utf-8")
    shutil.copyfile(FONT, run.path("work/Inter.ttf"))
    final = run.path("final/ad_9x16.mp4")
    _ffmpeg(run, "-i", "work/picture.mp4", "-i", "work/master.wav",
            "-vf", "ass=work/captions.ass:fontsdir=work,noise=alls=4:allf=t",
            *ENCODE, *BITRATE_CAP, "-c:a", "aac", "-b:a", "192k", run.rel(final))
    shutil.rmtree(run.dir / "work")
    return run.rel(final)
