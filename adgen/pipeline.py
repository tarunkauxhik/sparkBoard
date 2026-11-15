"""The 13 pipeline steps, brief to final QA.

Each step writes one JSON file in the run folder and is skipped on a re-run if
that file exists, so a run can be stopped and resumed at any point.
"""
import shutil
from pathlib import Path

import yaml

from adgen.editor import render_video, stream_seconds, validate_edit_list
from adgen.ledger import Ledger
from adgen.prompts import shot_prompt
from adgen.run import Run
from adgen.schemas import (
    Approval, Audio, Brief, Check, Clips, Concepts, EditList, FixedClip, Insights,
    Keyframes, Look, QAReport, Refs, Render, Storyboard, Take,
)
from adgen.statics import STATIC_SIZES, static_ad

PLAYBOOKS = Path(__file__).parent.parent / "playbooks"
# Which video model each storyboard route uses. "static" shots have no clip.
ROUTE_MODEL = {"veo_talk": "veo3_fast", "veo_broll": "veo3_lite",
               "vo_only": "veo3_lite", "avatar_talk": "kling_avatar"}


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

    def ask(task: str, cls, **ctx):
        return cls.model_validate(provider.chat_json(task, ctx))

    # 1 Brief
    brief = step("brief.json", Brief, lambda: (
        Brief.model_validate_json(brief_path.read_text("utf-8")), brief_path.name, "input brief"))
    b = brief.model_dump()

    # 2 Insights
    insights = step("insights.json", Insights, lambda: (
        ask("insights", Insights, brief=b), "insight bank", "from the brief and product knowledge"))

    # 3 Concepts (write, then critic scores and picks)
    def make_concepts():
        concepts = ask("concepts", Concepts, brief=b, insights=insights.model_dump())
        return concepts, concepts.winner.title, concepts.reason
    concepts = step("concepts.json", Concepts, make_concepts)

    # 4 Look, adapted from the category playbook
    def make_look():
        playbook = yaml.safe_load((PLAYBOOKS / f"{brief.category}.yaml").read_text("utf-8"))
        look = ask("look", Look, brief=b, concept=concepts.winner.model_dump(), playbook=playbook)
        why = "; ".join(f"{name}: {choice.reason}" for name, choice in look)
        return look, f"{look.mood.value}, {look.setting.value}", why
    look = step("look.json", Look, make_look)

    # 6 Storyboard (written before step 5, because references need the character list)
    def make_storyboard():
        board = ask("storyboard", Storyboard, brief=b, concept=concepts.winner.model_dump(),
                    look=look.model_dump())
        return board, f"{len(board.shots)} shots", "one shot per beat of the winning concept"
    board = step("storyboard.json", Storyboard, make_storyboard)

    # 5 References: use the brief's, or generate a portrait per character, a packshot, a location
    def make_refs():
        if brief.refs:
            return brief.refs, "user references", "provided in the brief"
        refs = Refs()
        for who in board.characters:
            out = run.path(f"refs/{who.name}.png")
            provider.image(f"Identity portrait: {who.description}, wearing {who.outfit}", [], out)
            refs.characters[who.name] = run.rel(out)
        out = run.path("refs/product.png")
        provider.image(f"Packshot of {brief.product} by {brief.brand}, plain background", [], out)
        refs.product.append(run.rel(out))
        out = run.path("refs/location.png")
        provider.image(f"Empty location plate: {look.setting.value}", [], out)
        refs.location = run.rel(out)
        return refs, "generated references", "none were provided in the brief"
    refs = step("refs.json", Refs, make_refs)

    # 7 Approve
    if not run.has("approval.json") and not auto_approve:
        print(f"\nStoryboard is ready: {run.path('storyboard.json')}")
        print(f"Edit it if you like, then continue with: --run-id {run.id} --auto-approve")
        return False
    step("approval.json", Approval, lambda: (
        Approval(approved=True, by="auto"), "approved", "--auto-approve was set"))

    # 8 Keyframes: one still per shot, with the same references every time
    def make_keyframes():
        files = {}
        for shot in board.shots:
            shot_refs = refs.product + [refs.location]
            if shot.character:
                shot_refs.append(refs.characters[shot.character])
            out = run.path(f"keyframes/{shot.id}.png")
            provider.image(shot_prompt(shot, board, look, brief), shot_refs, out)
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
            task_id = provider.video(shot_prompt(shot, board, look, brief),
                                     run.dir / keyframes.files[shot.id], out, model, shot.duration_s)
            takes.append(Take(shot_id=shot.id, take=1, file=run.rel(out), task_id=task_id, model=model))
        return Clips(takes=takes), f"{len(takes)} clips", "model picked by each shot's route"
    clips = step("clips.json", Clips, make_clips)
    shots = {shot.id: shot for shot in board.shots}

    # 10 Audio: swap talking clips to the character's fixed voice, then get word timings
    def make_audio():
        fixed = []
        for take in clips.takes:
            shot = shots[take.shot_id]
            src = run.dir / take.file
            out = run.path(f"clips/fixed/{shot.id}.mp4")
            words = []
            if shot.route == "veo_talk":
                voice = next(c.voice for c in board.characters if c.name == shot.speaker)
                provider.voice_change(src, out, voice, shot.duration_s)
                words = provider.transcribe(out, shot.dialogue_caption, shot.duration_s)
            else:
                shutil.copyfile(src, out)
            fixed.append(FixedClip(shot_id=shot.id, file=run.rel(out), words=words))
        return Audio(clips=fixed), "one voice per character", "voice changer keeps timing, so lip-sync holds"
    audio = step("audio.json", Audio, make_audio)

    # 11 Edit list
    def make_edit_list():
        clip_info = [{"shot_id": c.shot_id, "file": c.file, "duration_s": shots[c.shot_id].duration_s}
                     for c in audio.clips]
        edit = ask("edit_list", EditList, brief=b, clips=clip_info)
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
                    static_ad(run.dir / keyframes.files[shot.id], shot.dialogue_caption, brief.brand, size, out)
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

    run.write_decision_log_md()
    return True
