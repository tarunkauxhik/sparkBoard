"""ffmpeg editor: checks an edit list, then renders it into the final 9:16 video.

How the render avoids audio drift:
- every cut is first normalized to the same size, frame rate and pixel format;
- each cut's length is a whole number of frames, and its sound is cut to that exact length;
- the sound is joined into one master track and muxed once (never `-shortest`).
"""
import shutil
import subprocess
from pathlib import Path

from adgen.run import Run
from adgen.schemas import Audio, Cut, EditList
from adgen.statics import FONT, end_card

WIDTH, HEIGHT, FPS, SAMPLE_RATE = 1080, 1920, 24, 48000
MAX_AD_SECONDS = 60
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


def render_video(run: Run, edit: EditList, audio: Audio, brand: str) -> str:
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
    end_card(brand, edit.end_card.line, run.path("work/end_card.png"))
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
