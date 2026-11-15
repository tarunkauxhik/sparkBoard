"""The 13 pipeline steps, brief to final QA.

Each step writes one JSON file in the run folder and is skipped on a re-run if
that file exists, so a run can be stopped and resumed at any point.
"""
import shutil
from pathlib import Path

import yaml
from pydantic import ValidationError

from adgen.brain import TASKS
from adgen.casting import casting_errors, used_personas
from adgen.editor import render_video, stream_seconds, validate_edit_list
from adgen.ledger import Ledger
from adgen.prompts import (
    character_sheet_prompt, keyframe_request, location_prompt, motion_prompt, packshot_prompt,
)
from adgen.report import write_decision_log_md, write_storyboard_md
from adgen.rules import LENGTH_TOLERANCE_S, look_errors, review_errors, storyboard_errors
from adgen.run import Run
from adgen.schemas import (
    Approval, Audio, Brief, Check, Clips, Concept, Concepts, EditList, FixedClip, Insights,
    Keyframes, Look, QAReport, Refs, Render, Storyboard, StoryboardReview, Take,
)
from adgen.statics import STATIC_SIZES, static_ad

PLAYBOOKS = Path(__file__).parent.parent / "playbooks"
# Which video model each storyboard route uses. "static" shots have no clip.
ROUTE_MODEL = {"veo_talk": "veo3_fast", "veo_broll": "veo3_lite",
               "vo_only": "veo3_lite", "avatar_talk": "kling_avatar"}
SCHEMA_TRIES = 2  # one try, plus one more with the errors sent back. Never a loop.


def run_pipeline(brief_path: Path, run: Run, provider, ledger: Ledger, auto_approve: bool) -> bool:
    """Runs every step that is not done yet. Returns False if it stopped for approval."""

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
        used = [] if getattr(provider, "placeholder_cast", False) else used_personas(brief.brand, run.dir.parent)
        look = ask("look", brief=b, concept=winner, playbook=playbook, used_personas=used,
                   check=lambda look: look_errors(look, brief) + casting_errors(look, used))
        why = "; ".join(f"{name}: {choice.reason}" for name, choice in look if name != "cast")
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

    # 7 Approve
    if not run.has("approval.json") and not auto_approve:
        print(f"\nStoryboard is ready to review: {run.path('storyboard.md')}")
        print(f"Edit storyboard.json if you like, then continue with: --run-id {run.id} --auto-approve")
        return False
    step("approval.json", Approval, lambda: (
        Approval(approved=True, by="auto"), "approved", "--auto-approve was set"))

    # 5 References: use the brief's, or generate a character sheet per on-screen cast member,
    #   a clean packshot and a location plate
    def make_refs():
        if brief.refs:
            return brief.refs, "user references", "provided in the brief"
        refs = Refs()
        on_screen = {shot.character for shot in board.shots if shot.character}
        for who in look.cast:
            if who.name in on_screen:
                out = run.path(f"refs/{who.name}_sheet.png")
                provider.image(character_sheet_prompt(who), [], out)
                refs.characters[who.name] = run.rel(out)
        out = run.path("refs/product.png")
        provider.image(packshot_prompt(brief), [], out)
        refs.product.append(run.rel(out))
        out = run.path("refs/location.png")
        provider.image(location_prompt(look, brief), [], out)
        refs.location = run.rel(out)
        return refs, "generated references", "none were provided in the brief"
    refs = step("refs.json", Refs, make_refs)

    # 8 Keyframes: one still per shot, with the same references every time
    def make_keyframes():
        files = {}
        for shot in board.shots:
            prompt, shot_refs = keyframe_request(shot, look, brief, refs)
            out = run.path(f"keyframes/{shot.id}.png")
            provider.image(prompt, shot_refs, out)
            files[shot.id] = run.rel(out)
        return Keyframes(files=files), f"{len(files)} keyframes", "keyframe first, then video"
    keyframes = step("keyframes.json", Keyframes, make_keyframes)

    # 9 Clips: every take is kept in clips/raw/ and never overwritten
    def make_clips():
        takes = []
        for shot in board.shots:
            if shot.route == "static":
                continue
            model = ROUTE_MODEL[shot.route]
            out = run.path(f"clips/raw/{shot.id}_take1.mp4")
            task_id = provider.video(motion_prompt(shot, look, brief), run.dir / keyframes.files[shot.id],
                                     out, model, shot.duration_s)
            takes.append(Take(shot_id=shot.id, take=1, file=run.rel(out), task_id=task_id, model=model))
        return Clips(takes=takes), f"{len(takes)} clips", "model picked by each shot's route"
    clips = step("clips.json", Clips, make_clips)
    shots = {shot.id: shot for shot in board.shots}

    # 10 Audio: swap talking clips to the speaker's fixed voice, then get word timings
    def make_audio():
        fixed = []
        for take in clips.takes:
            shot = shots[take.shot_id]
            src = run.dir / take.file
            out = run.path(f"clips/fixed/{shot.id}.mp4")
            words = []
            if shot.route == "veo_talk":
                voice = next(member.voice for member in look.cast if member.name == shot.speaker)
                provider.voice_change(src, out, voice, shot.duration_s)
                words = provider.transcribe(out, shot.dialogue_caption, shot.duration_s)
            else:
                shutil.copyfile(src, out)
            fixed.append(FixedClip(shot_id=shot.id, file=run.rel(out), words=words))
        return Audio(clips=fixed), "one voice per cast member", "voice changer keeps timing, so lip-sync holds"
    audio = step("audio.json", Audio, make_audio)

    # 11 Edit list
    def make_edit_list():
        clip_info = [{"shot_id": c.shot_id, "file": c.file, "duration_s": shots[c.shot_id].duration_s}
                     for c in audio.clips]
        edit = ask("edit_list", brief=b, clips=clip_info)
        edit.end_card.line = board.end_card_line  # the claim-checked line from the storyboard
        return edit, f"{len(edit.cuts)} cuts + end card", "; ".join(c.reason for c in edit.cuts)
    edit = step("edit_list.json", EditList, make_edit_list)

    # 12 Render: code checks the edit list, then ffmpeg builds the video; static shots become static ads
    def make_render():
        errors = validate_edit_list(edit, audio, run)
        if errors:
            raise ValueError("edit list is not valid:\n" + "\n".join(errors))
        files = [render_video(run, edit, audio, brief.brand)]
        for shot in board.shots:
            if shot.route == "static":
                for name, size in STATIC_SIZES.items():
                    out = run.path(f"statics/{shot.id}_{name}.png")
                    static_ad(run.dir / keyframes.files[shot.id], shot.headline, brief.brand, size, out)
                    files.append(run.rel(out))
        return Render(files=files), f"{len(files)} file(s)", "edit list passed validation"
    render = step("render.json", Render, make_render)

    # 13 Final QA
    def make_qa():
        final = run.dir / render.files[0]
        review = provider.review(final, "final_cut")
        gap = abs(stream_seconds(final, "v:0") - stream_seconds(final, "a:0"))
        checks = [
            Check(name="picture and sound are the same length", passed=gap < 0.1, detail=f"{gap:.3f} s apart"),
            Check(name="final cut review", passed=review["passed"], detail=review["detail"]),
        ]
        report = QAReport(passed=all(c.passed for c in checks), checks=checks)
        return report, "pass" if report.passed else "fail", "; ".join(c.name for c in checks if not c.passed)
    step("qa_report.json", QAReport, make_qa)

    write_decision_log_md(run)
    return True
