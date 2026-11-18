"""The 13 pipeline steps, brief to final QA.

Each step writes one JSON file in the run folder and is skipped on a re-run if
that file exists, so a run can be stopped and resumed at any point. Inside the
generation steps every image and clip that already exists is kept too, so a step
that stopped halfway (for example at the budget cap) does not pay twice.
"""
import shutil
import subprocess
from pathlib import Path

import yaml
from pydantic import ValidationError

from adgen.brain import TASKS
from adgen.casting import casting_errors, other_sheets, used_personas
from adgen.clicks import find_clicks
from adgen.editor import (
    TRIM_PAD_S, build_edit_list, clean_voice, duck_clicks, final_checks, grab_frame, lay_voiceover, render_video,
    stream_seconds, validate_edit_list,
)
from adgen.ledger import Ledger
from adgen.prompts import (
    AUDIO_TAG, character_sheet_prompt, keyframe_request, location_prompt, motion_prompt, packshot_prompt,
)
from adgen.qa import (
    CLIP_FACE_MIN, CLIP_TRIES, KEYFRAME_FACE_MIN, KEYFRAME_TRIES, MAX_PITCH_GAP, MAX_WORD_ERROR_RATE,
    PERSONA_FACE_MAX, face_passes, last_word_heard, word_error_rate,
)
from adgen.report import write_decision_log_md, write_storyboard_md
from adgen.rules import LENGTH_TOLERANCE_S, look_errors, review_errors, storyboard_errors
from adgen.run import Run
from adgen.schemas import (
    EDGE_SILENCE_S, Approval, Audio, Brief, Check, Clips, Concept, Concepts, EditList, FixedClip, Insights,
    Keyframes, KeyframeTake, Look, QAReport, Refs, Render, Shot, Storyboard, StoryboardReview, Take, Word,
)
from adgen.statics import STATIC_SIZES, app_screen, static_ad, write_label
from adgen.voice import median_pitch_hz

PLAYBOOKS = Path(__file__).parent.parent / "playbooks"
# Which video model each storyboard route uses. "static" shots have no clip.
# Veo 3.1 Lite is the default for every clip (half the price of Fast). Kling Avatar is only a
# documented fallback: in the smoke test its speaker turned away and the lip-sync was off.
ROUTE_MODEL = {"veo_talk": "veo3_lite", "veo_broll": "veo3_lite",
               "vo_only": "veo3_lite", "avatar_talk": "kling_avatar"}
SCHEMA_TRIES = 2  # one try, plus one more with the errors sent back. Never a loop.
VO_START_S = EDGE_SILENCE_S  # a narrator starts half a second into the shot
STAGES = ("refs", "keyframes", "clips")  # a live run can stop after any of these for a look


def word_problems(shot: Shot, words: list[Word]) -> tuple[float, list[str]]:
    """(word error rate, problems) of a transcript against the shot's line."""
    heard, voice_line = " ".join(w.word for w in words), AUDIO_TAG.sub(" ", shot.dialogue_tts)
    rate = round(word_error_rate(shot.dialogue_caption, heard, voice_line), 2)
    if rate > MAX_WORD_ERROR_RATE:
        return rate, [f"words: heard {heard!r} ({rate:.0%} wrong)"]
    if not last_word_heard(shot.dialogue_caption, heard, voice_line):
        return rate, [f"words: the last word was cut off (heard {heard!r})"]
    return rate, []


def check_clip(provider, run: Run, shot: Shot, take: Take, keyframe: Path, other_sheets_: list[Path]) -> Take:
    """Fill in a take's check results: the words Veo spoke (veo_talk) and the face (if one shows).
    A vo_only take arrives with its narrator's words already set; they place the face check."""
    clip = run.dir / take.file
    if shot.route == "veo_talk":
        take.words = [Word(**word) for word in provider.transcribe(clip, shot.dialogue_caption, shot.duration_s)]
        take.word_error_rate, problems = word_problems(shot, take.words)
        take.problems += problems
    if shot.character and shot.face_visible:
        # Check the face where it matters: across the spoken part, or across the middle of a silent shot.
        start, end = ((take.words[0].start_s, take.words[-1].end_s) if take.words
                      else (shot.duration_s * 0.25, shot.duration_s * 0.75))
        scores = []
        for second in (start, (start + end) / 2, end):
            frame = grab_frame(clip, second, run.path(f"clips/frames/{clip.stem}_{second:.1f}s.png"))
            own = provider.faces.similarity(keyframe, frame)
            others = [provider.faces.similarity(sheet, frame) or 0.0 for sheet in other_sheets_]
            scores.append(own)
            if not face_passes(own, others, CLIP_FACE_MIN):
                take.problems.append(f"face: {'not found' if own is None else f'{own:.2f}'} at {second:.1f} s "
                                     f"(needs {CLIP_FACE_MIN} and closer than any other persona)")
        take.face = None if None in scores else round(min(scores), 3)
    return take


def run_pipeline(brief_path: Path, run: Run, provider, ledger: Ledger, auto_approve: bool,
                 stop_after: str | None = None, isolate_voice: bool = False, trim_pad: float = TRIM_PAD_S,
                 stop_on_failure: bool = False) -> bool:
    """Runs every step that is not done yet. Returns False if it stopped early: for
    storyboard approval, after the stage named in `stop_after`, or (with `stop_on_failure`)
    when a shot failed every retry."""

    def step(name: str, cls, make):
        """Run one step, or load its saved output. `make` returns (result, choice, reason)."""
        if run.has(name):
            print(f"  skip  {name}")
            return run.load(name, cls)
        spent_before = ledger.total()
        result, choice, reason = make()
        run.save(name, result)
        run.log(name.removesuffix(".json"), choice, reason, ledger.total() - spent_before)
        print(f"  done  {name}")
        return result

    def ask(task: str, check=None, **ctx):
        """One LLM task. The reply must pass the schema and the code rules in `check`."""
        feedback = ""
        for _ in range(SCHEMA_TRIES):
            try:
                result = TASKS[task].schema.model_validate(provider.chat_json(task, ctx, feedback))
                errors = check(result) if check else []
            except ValidationError as error:  # a schema rule; keep only the plain messages
                errors = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors()]
            except ValueError as error:  # the reply was not JSON
                errors = [str(error)]
            if not errors:
                return result
            feedback = "\n".join(errors)
        raise ValueError(f"{task}: still not valid after {SCHEMA_TRIES} tries:\n{feedback}")

    def stop_here(stage: str) -> bool:
        if stop_after == stage:
            print(f"\nStopped after {stage}, as asked. Continue with: --run-id {run.id}")
        return stop_after == stage

    # 1 Brief
    brief = step("brief.json", Brief, lambda: (
        Brief.model_validate_json(brief_path.read_text("utf-8")), brief_path.name, "input brief"))
    b = brief.model_dump(exclude_none=True)

    # 2 Insights
    insights = step("insights.json", Insights, lambda: (
        ask("insights", brief=b), "insight bank", "from the brief and product knowledge"))

    # 3 Concepts: one call writes five, a separate critic call scores them, code picks the top score
    def make_concepts():
        drafts = ask("concepts", brief=b, insights=insights.model_dump()).concepts
        ids = {d.id for d in drafts}
        review = ask("concept_critic", brief=b, concepts=[d.model_dump() for d in drafts],
                     check=lambda r: [] if {x.id for x in r.reviews} == ids
                     else [f"return exactly one review for each of {sorted(ids)}"])
        scored = {x.id: x for x in review.reviews}
        concepts = [Concept(**d.model_dump(), scores=scored[d.id].scores, note=scored[d.id].note)
                    for d in drafts]
        winner = max(concepts, key=lambda c: c.scores.total)
        result = Concepts(concepts=concepts, winner_id=winner.id, reason=winner.note)
        return result, f"{winner.title} ({winner.scores.total}/50)", winner.note
    concepts = step("concepts.json", Concepts, make_concepts)
    winner = concepts.winner.model_dump()

    # 4 Look and cast, adapted from the category playbook
    def make_look():
        playbook = yaml.safe_load((PLAYBOOKS / f"{brief.category}.yaml").read_text("utf-8"))
        # The mock's people are placeholders, so cast variety is only checked for real casts.
        used = [] if provider.placeholder_cast else used_personas(brief.brand, run.dir.parent)
        look = ask("look", brief=b, concept=winner, playbook=playbook, used_personas=used,
                   check=lambda look: look_errors(look, brief) + casting_errors(look, used))
        why = "; ".join(f"{name}: {choice.reason}" for name, choice in look.choices())
        cast = ", ".join(member.name for member in look.cast)
        return look, f"{look.mood.value}; {look.setting.value}; cast: {cast}", why
    look = step("look.json", Look, make_look)

    # 6 Storyboard: draft, then a critic rewrite. Both must pass the code rules.
    #   (Written before step 5, because references are only made for cast who appear on screen.)
    def make_storyboard():
        length_s = {"min": brief.target_length_s - LENGTH_TOLERANCE_S,
                    "max": brief.target_length_s + LENGTH_TOLERANCE_S}
        if run.has("storyboard_draft.json"):  # a paid draft is never written twice
            draft = run.load("storyboard_draft.json", Storyboard)
        else:
            draft = ask("storyboard", brief=b, length_s=length_s, concept=winner, insights=insights.model_dump(),
                        look=look.model_dump(), check=lambda board: storyboard_errors(board, brief, look))
            run.save("storyboard_draft.json", draft)
        review = ask("storyboard_critic", brief=b, length_s=length_s, look=look.model_dump(),
                     storyboard=draft.model_dump(),
                     check=lambda r: review_errors(r, brief, look))
        run.save("storyboard_critic.json", review)
        board = review.storyboard
        notes = "; ".join(f"{n.shot_id}: {n.issue}" for n in review.notes) or "the critic changed nothing"
        return (board, f"{len(board.shots)} shots, hook type {board.hook_type}, {len(review.notes)} critic notes",
                f"hook: {board.hook_reason} Critic: {notes}")
    board = step("storyboard.json", Storyboard, make_storyboard)
    errors = storyboard_errors(board, brief, look)  # checked again in case it was edited by hand
    if errors:
        raise ValueError("storyboard.json breaks the rules:\n" + "\n".join(errors))
    write_storyboard_md(run, brief, concepts, look, board, run.load("storyboard_critic.json", StoryboardReview))
    shots = {shot.id: shot for shot in board.shots}

    # 7 Approve
    if not run.has("approval.json") and not auto_approve:
        print(f"\nStoryboard is ready to review: {run.path('storyboard.md')}")
        print(f"Edit storyboard.json if you like, then continue with: --run-id {run.id} --auto-approve")
        return False
    step("approval.json", Approval, lambda: (
        Approval(approved=True, by="auto"), "approved", "--auto-approve was set"))

    # 5 References: use the brief's, or make a character sheet per on-screen cast member,
    #   a clean packshot (or the app screen, drawn in code) and a location plate.
    def make_refs():
        if brief.refs:
            return brief.refs, "user references", "provided in the brief"
        refs, notes = Refs(), []
        on_screen = {shot.character for shot in board.shots if shot.character}
        for who in look.cast:
            if who.name not in on_screen:
                continue
            sheet = run.path(f"refs/{who.name}_sheet.png")
            if not sheet.exists():
                provider.image(character_sheet_prompt(who), [], sheet, "16:9")
            # Different personas must look different: against this cast and other brands' sheets.
            known = [(name, run.dir / path) for name, path in refs.characters.items()]
            for other, other_sheet in known + other_sheets(brief.brand, run.dir.parent):
                alike = provider.faces.closest_views(sheet, other_sheet)
                if alike is not None and alike >= PERSONA_FACE_MAX:
                    raise ValueError(f"{who.name}'s character sheet looks too much like {other}'s "
                                     f"({alike:.2f}, the limit is {PERSONA_FACE_MAX}). Re-cast {who.name}: "
                                     "delete look.json and the storyboard files, then run again.")
                notes.append(f"{who.name} vs {other}: {'no face' if alike is None else f'{alike:.2f}'}")
            refs.characters[who.name] = run.rel(sheet)
        product = run.path("refs/product.png")
        if brief.app_screen:  # an app: its screen is drawn in code, so every word on it is exact
            app_screen(brief, product)
        elif not product.exists():
            provider.image(packshot_prompt(brief), [], product, "1:1")
        refs.product.append(run.rel(product))
        location = run.path("refs/location.png")
        if not location.exists():
            provider.image(location_prompt(look, brief), [], location)
        refs.location = run.rel(location)
        return refs, "generated references", "; ".join(notes) or "no faces to compare"
    refs = step("refs.json", Refs, make_refs)
    if stop_here("refs"):
        return False

    def sheets_of_others(shot: Shot) -> list[Path]:
        return [run.dir / path for name, path in refs.characters.items() if name != shot.character]

    # 8 Keyframes: one still per shot from the same references. A shot that shows a face is
    #   checked against the character sheet and re-made up to KEYFRAME_TRIES times.
    def make_keyframes():
        files, takes, labels = {}, [], []
        for shot in board.shots:
            prompt, shot_refs = keyframe_request(shot, look, brief, refs)
            shows_face = bool(shot.character and shot.face_visible)
            best = None
            for number in range(1, KEYFRAME_TRIES + 1):
                out = run.path(f"keyframes/{shot.id}_take{number}.png")
                if not out.exists():
                    provider.image(prompt, [run.dir / ref for ref in shot_refs], out)
                take = KeyframeTake(shot_id=shot.id, take=number, file=run.rel(out))
                if shows_face:
                    take.face = provider.faces.similarity(run.dir / refs.characters[shot.character], out)
                    others = [provider.faces.similarity(sheet, out) or 0.0 for sheet in sheets_of_others(shot)]
                    take.passed = face_passes(take.face, others, KEYFRAME_FACE_MIN)
                    take.face = None if take.face is None else round(take.face, 3)
                takes.append(take)
                if best is None or take.passed or (take.face or 0) > (best.face or 0):
                    best = take
                if take.passed:
                    break
            files[shot.id] = best.file
            if shot.blank_label_text:  # write the exact label text into the blank area, before Veo
                box = provider.find_label_area(run.dir / best.file)
                if box:
                    labelled = run.path(f"keyframes/{shot.id}_labelled.png")
                    write_label(run.dir / best.file, shot.blank_label_text, box, labelled)
                    files[shot.id] = run.rel(labelled)
                    labels.append(f"{shot.id}: wrote {shot.blank_label_text!r}")
                else:
                    labels.append(f"{shot.id}: no blank label area found, text not written")
        failed = sorted({t.shot_id for t in takes} - {t.shot_id for t in takes if t.passed})
        notes = [f"face check failed on every try for: {', '.join(failed)}" if failed else "every keyframe passed"]
        return (Keyframes(files=files, takes=takes), f"{len(files)} keyframes from {len(takes)} tries",
                "; ".join(notes + labels))
    keyframes = step("keyframes.json", Keyframes, make_keyframes)
    failed_frames = sorted({t.shot_id for t in keyframes.takes} - {t.shot_id for t in keyframes.takes if t.passed})
    if stop_on_failure and failed_frames:
        print(f"\nStopped: the face check failed on every try for {', '.join(failed_frames)}. "
              "See keyframes.json; delete it to try again, or continue without --stop-on-failure.")
        return False
    if stop_here("keyframes"):
        return False

    def narrate(shot: Shot) -> tuple[str, list[Word], list[str]]:
        """The narrator's line for a vo_only shot, made once: (file, words in clip time, problems)."""
        voice = run.path(f"clips/voice/{shot.id}.mp3")
        if not voice.exists():
            voice_id, _ = provider.narrator_voice(next(m for m in look.cast if m.name == shot.speaker))
            provider.speak(shot.dialogue_tts, voice, voice_id)
        spoken = provider.transcribe(voice, shot.dialogue_caption, stream_seconds(voice, "a:0"))
        words = [Word(word=w["word"], start_s=round(w["start_s"] + VO_START_S, 2),
                      end_s=round(w["end_s"] + VO_START_S, 2)) for w in spoken]
        _, problems = word_problems(shot, words)
        if words and words[-1].end_s > shot.duration_s - 0.1:
            problems.append(f"voiceover: the line ends at {words[-1].end_s:.1f} s, past the {shot.duration_s} s shot")
        return run.rel(voice), words, problems

    # 9 Clips: every take is kept in clips/raw/ and never overwritten. Each take is checked
    #   (words, face); a failed take gets one more try, then the shot is flagged.
    def make_clips():
        takes = []
        for shot in board.shots:
            if shot.route == "static":
                continue
            keyframe = run.dir / keyframes.files[shot.id]
            voice_file, voice_words, voice_problems = narrate(shot) if shot.route == "vo_only" else ("", [], [])
            for number in range(1, CLIP_TRIES + 1):
                out = run.path(f"clips/raw/{shot.id}_take{number}.mp4")
                task_id = "made in an earlier run"
                if not out.exists():
                    task_id = provider.video(motion_prompt(shot, look, brief), keyframe, out,
                                             ROUTE_MODEL[shot.route], shot.duration_s)
                take = Take(shot_id=shot.id, take=number, file=run.rel(out), task_id=task_id,
                            model=ROUTE_MODEL[shot.route], voice_file=voice_file, words=voice_words)
                takes.append(check_clip(provider, run, shot, take, keyframe, sheets_of_others(shot)))
                take.problems = voice_problems + take.problems
                # A new clip fixes what Veo did; it cannot fix the narrator's line (TTS), so in a
                # vo_only shot only picture problems get a retake.
                left = [p for p in take.problems if not p.startswith(("words:", "voiceover:"))]                     if shot.route == "vo_only" else take.problems
                if not left:
                    break
        clips = Clips(takes=takes)
        flagged = [f"{t.shot_id}: {'; '.join(t.problems)}" for t in clips.chosen().values() if not t.passed]
        return (clips, f"{len(clips.chosen())} clips from {len(takes)} takes",
                "flagged: " + " | ".join(flagged) if flagged else "every clip passed its checks")
    clips = step("clips.json", Clips, make_clips)
    failed_clips = [f"{t.shot_id} ({'; '.join(t.problems)})" for t in clips.chosen().values() if not t.passed]
    if stop_on_failure and failed_clips:
        print(f"\nStopped: every take failed its checks for {' | '.join(failed_clips)}. "
              "See clips.json; continue without --stop-on-failure to render anyway.")
        return False
    if stop_here("clips"):
        return False

    # 10 Audio: Veo's own voice is kept. Optionally the voice isolator removes room echo first.
    #   Stray clicks and taps between the words are muted (isolated voice) or ducked (Veo audio).
    def make_audio():
        fixed, removed = [], []
        for take in clips.chosen().values():
            source, out = run.dir / take.file, run.path(f"clips/fixed/{take.shot_id}.mp4")
            clicks, route = [], shots[take.shot_id].route
            if route == "vo_only":  # the narrator over the clip's own quiet sound
                mixed = run.path(f"clips/fixed/{take.shot_id}_mixed.mp4")
                lay_voiceover(source, run.dir / take.voice_file, mixed, VO_START_S)
                if clicks := find_clicks(mixed, take.words):
                    duck_clicks(mixed, out, clicks)
                else:
                    shutil.copyfile(mixed, out)
                mixed.unlink()
            elif isolate_voice and take.words:
                voice = run.path(f"clips/fixed/{take.shot_id}_voice.mp3")
                if not voice.exists():
                    provider.isolate(source, voice, shots[take.shot_id].duration_s)
                clicks = find_clicks(voice, take.words)
                clean_voice(source, voice, out, clicks)
                # A second pass over the finished mix: the quiet bed changes what stands out.
                if more := find_clicks(out, take.words):
                    mixed = out.with_name(f"{out.stem}_first_pass.mp4")
                    out.rename(mixed)
                    duck_clicks(mixed, out, more)
                    mixed.unlink()
                    clicks += more
            elif take.words and (clicks := find_clicks(source, take.words)):
                duck_clicks(source, out, clicks)
            else:
                shutil.copyfile(source, out)
            removed += [f"{take.shot_id} at {start:.2f} s" for start, _ in clicks]
            fixed.append(FixedClip(shot_id=take.shot_id, file=run.rel(out), words=take.words, clicks_removed=clicks))
        return (Audio(clips=fixed), "isolated voice over a room-tone bed" if isolate_voice else "Veo's own audio",
                f"clicks removed: {', '.join(removed) or 'none'}; word timings drive the trims and captions")
    audio = step("audio.json", Audio, make_audio)

    # 11 Edit list: built by code. Straight cuts, spoken clips trimmed to their words.
    def make_edit_list():
        durations = {clip.shot_id: stream_seconds(run.dir / clip.file, "v:0") for clip in audio.clips}
        edit = build_edit_list(audio, durations, board.end_card_line, trim_pad)
        return edit, f"{len(edit.cuts)} cuts + end card", "; ".join(f"{c.shot_id}: {c.reason}" for c in edit.cuts)
    edit = step("edit_list.json", EditList, make_edit_list)

    # 12 Render: code checks the edit list, then ffmpeg builds the video; static shots become static ads
    def make_render():
        errors = validate_edit_list(edit, audio, run)
        if errors:
            raise ValueError("edit list is not valid:\n" + "\n".join(errors))
        files = [render_video(run, edit, audio, brief.brand, run.dir / refs.product[0] if refs.product else None)]
        for shot in board.shots:
            if shot.route == "static":
                for name, size in STATIC_SIZES.items():
                    out = run.path(f"statics/{shot.id}_{name}.png")
                    static_ad(run.dir / keyframes.files[shot.id], shot.headline, brief.brand, size, out)
                    files.append(run.rel(out))
        return Render(files=files), f"{len(files)} file(s)", "edit list passed validation"
    render = step("render.json", Render, make_render)

    # 13 Final QA: code checks on the finished video, everything the retry loops flagged,
    #   the voice match between a speaker's clips, and a Gemini review as hints only.
    def make_qa():
        final = run.dir / render.files[0]
        checks = final_checks(final, edit.end_card.duration_s)
        failed_frames = sorted({t.shot_id for t in keyframes.takes} - {t.shot_id for t in keyframes.takes if t.passed})
        checks.append(Check(name="keyframe faces match their character sheets", passed=not failed_frames,
                            detail=f"failed: {', '.join(failed_frames)}" if failed_frames else ""))
        for take in clips.chosen().values():
            if not take.passed:
                checks.append(Check(name=f"clip {take.shot_id} passed its checks", passed=False,
                                    detail="; ".join(take.problems)))
        kept = {cut.shot_id: (cut.in_s, cut.out_s) for cut in edit.cuts}
        for clip in audio.clips:  # after removal, no click may be left between the words the ad keeps
            if clip.words:
                left = find_clicks(run.dir / clip.file, clip.words, within=kept[clip.shot_id])
                checks.append(Check(name=f"no clicks or taps between the words in {clip.shot_id}", passed=not left,
                                    detail=(f"left at {', '.join(f'{s:.2f} s' for s, _ in left)}" if left else
                                            f"removed {len(clip.clicks_removed)}")))
        pitches = {}  # speaker -> the pitch of each of their clips
        for clip in audio.clips:
            if clip.words:
                pitch = median_pitch_hz(run.dir / clip.file, clip.words[0].start_s, clip.words[-1].end_s)
                if pitch:
                    pitches.setdefault(shots[clip.shot_id].speaker, {})[clip.shot_id] = round(pitch)
        for speaker, by_shot in pitches.items():
            gap = max(by_shot.values()) / min(by_shot.values()) - 1
            checks.append(Check(name=f"{speaker}'s voice has the same pitch in every clip",
                                passed=gap <= MAX_PITCH_GAP, detail=f"{by_shot} Hz, {gap:.0%} apart"))
        small = run.path("final/review_480p.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(final), "-vf", "scale=-2:480",
                        "-c:a", "aac", str(small)], check=True)
        notes = provider.review(small, stream_seconds(small, "v:0"))
        checks.append(Check(name="Gemini review (hints only, never a fail)", passed=True, detail=notes))
        report = QAReport(passed=all(c.passed for c in checks), checks=checks)
        return report, "pass" if report.passed else "fail", "; ".join(c.name for c in checks if not c.passed)
    step("qa_report.json", QAReport, make_qa)

    write_decision_log_md(run)
    return True
