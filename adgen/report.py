"""Readable copies of a run's JSON: storyboard.md and decision_log.md."""
import json

from adgen.prompts import keyframe_prompt, motion_prompt
from adgen.run import Run
from adgen.schemas import Brief, Concepts, Look, Storyboard, StoryboardReview


def write_storyboard_md(run: Run, brief: Brief, concepts: Concepts, look: Look,
                        board: Storyboard, review: StoryboardReview) -> None:
    """The storyboard for review: concept, look, cast, critic notes, then every shot with its prompts."""
    total = sum(shot.duration_s for shot in board.shots if shot.route != "static")
    winner = concepts.winner
    out = [
        f"# {board.title}",
        f"{brief.brand} {brief.product} | {brief.format} | {brief.platform} | {brief.language} | "
        f"{total} s + end card (target {brief.target_length_s} s)",
        "", "## Concept",
        f"**{winner.title}** (score {winner.scores.total}/50). {winner.summary}",
        f"Why it won: {concepts.reason}",
        "", "| Concept | Hook | Fit | Platform | Feasible | Distinct | Total |", "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for c in sorted(concepts.concepts, key=lambda c: -c.scores.total):
        s = c.scores
        out.append(f"| {c.title} | {s.hook} | {s.brief_fit} | {s.platform_fit} | {s.feasibility} | "
                   f"{s.distinctiveness} | {s.total} |")
    out += ["", "## Look"]
    out += [f"- **{name}**: {choice.value} ({choice.reason})" for name, choice in look if name != "cast"]
    out += ["", "## Cast"]
    out += [f"- **{m.name}**, {m.age}: {m.look}. Outfit: {m.outfit}. Voice: {m.voice}." for m in look.cast]
    out += ["", "## Critic notes"]
    out += [f"- {n.shot_id} ({n.kind}): {n.issue} Change: {n.change}" for n in review.notes] or ["- none"]
    out += ["", "## Claims check"]
    out += [f"- {c.shot_id}: \"{c.claim}\" is backed by the fact \"{brief.product_facts[c.fact]}\""
            if c.claim else f"- {c.shot_id}: no product claim" for c in review.line_checks]
    for shot in board.shots:
        out += ["", f"## {shot.id}: {shot.purpose}, {shot.duration_s} s, {shot.route}",
                f"- Shot: {shot.shot_type}, {shot.angle}, {shot.framing}",
                f"- On screen: {shot.character or 'no one'}; product visible: {'yes' if shot.product_visible else 'no'}",
                f"- First frame: {shot.first_frame}",
                f"- Action: {shot.action}",
                f"- Expression: {shot.expression or 'n/a'}; lighting: {shot.lighting}; camera: {shot.camera_move or 'static'}"]
        if shot.dialogue_tts:
            out += [f"- **{shot.speaker}** ({shot.dialogue_lang}): \"{shot.dialogue_tts}\"",
                    f"- Caption: \"{shot.dialogue_caption}\" ({len(shot.dialogue_caption.split())} words)"]
        if shot.headline:
            out.append(f"- Headline: {shot.headline}")
        out += [f"- Keyframe prompt: {keyframe_prompt(shot, look, brief)}",
                f"- Motion prompt: {motion_prompt(shot)}"]
    run.path("storyboard.md").write_text("\n".join(out) + "\n", "utf-8")


def write_decision_log_md(run: Run) -> None:
    """Readable copy of decision_log.jsonl, for the sample deliverables."""
    lines = ["# Decision log", "", "| Step | Choice | Reason | Cost |", "| --- | --- | --- | --- |"]
    for raw in run.path("decision_log.jsonl").read_text("utf-8").splitlines():
        e = json.loads(raw)
        lines.append(f"| {e['step']} | {e['choice']} | {e['reason']} | ${e['cost']:.3f} |")
    run.path("decision_log.md").write_text("\n".join(lines) + "\n", "utf-8")
