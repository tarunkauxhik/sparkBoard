"""Readable copies of a run's JSON: storyboard.md and decision_log.md."""
import json
import re

from adgen.prompts import keyframe_request, motion_prompt
from adgen.run import Run
from adgen.schemas import Brief, Concepts, Look, Refs, Storyboard, StoryboardReview


def write_storyboard_md(run: Run, brief: Brief, concepts: Concepts, look: Look,
                        board: Storyboard, review: StoryboardReview) -> None:
    """The storyboard for review: concept, look, cast, critic notes, then every shot with its prompts."""
    total = board.length_s
    winner = concepts.winner
    product = brief.product if brief.product.startswith(brief.brand) else f"{brief.brand} {brief.product}"
    out = [
        f"# {board.title}",
        f"{product} | {brief.format} | {brief.platform} | {brief.language} | "
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
    out += [f"- **{m.name}**, {m.age}: {m.look}. Outfit: {m.outfit}. Voice: {m.voice}; accent: {m.accent}; "
            f"pace: {m.pace}; energy: {m.energy}. Speech habits: {'; '.join(m.speech_habits)}." for m in look.cast]
    out += ["", "## Hook", f"Type: **{board.hook_type}**. {board.hook_reason}"]
    out += ["", "## Length", f"{board.counts} (counted by code). End card line: \"{board.end_card_line}\""]
    out += ["", "## Critic notes"]
    out += [f"- {n.shot_id} ({n.kind}): {n.issue} Change: {n.change}" for n in review.notes] or ["- none"]
    out += ["", "## Claims check"]
    for check in review.line_checks:
        out += [f"- {check.shot_id}: \"{c.claim}\" is backed by the fact \"{brief.product_facts[c.fact]}\""
                for c in check.claims] or [f"- {check.shot_id}: no product claim"]
    # Placeholder reference names, so the prompts below read the way the image model will get them.
    refs = Refs(characters={m.name: f"refs/{m.name}_sheet.png" for m in look.cast},
                product=["refs/product.png"], location="refs/location.png")
    for shot in board.shots:
        out += ["", f"## {shot.id}: {shot.purpose}, {shot.duration_s} s, {shot.route}",
                f"- Shot: {shot.shot_type}, {shot.angle}, {shot.framing}",
                f"- On screen: {shot.character or 'no one'}; product visible: {'yes' if shot.product_visible else 'no'}",
                f"- First frame: {shot.first_frame}",
                *[f"- Beat {b.start_s:g}-{b.end_s:g} s: {b.action}" + (f" ({b.eye_line})" if b.eye_line else "")
                  for b in shot.beats],
                f"- Setting: {shot.setting}",
                f"- Lens: {shot.lens}; lighting: {shot.lighting}; camera: {shot.camera_move or 'static'}; "
                f"sound: {shot.audio_notes}"]
        if shot.blank_label_text:
            out.append(f"- Added in code later (label area left blank): \"{shot.blank_label_text}\"")
        if shot.dialogue_tts:
            out += [f"- **{shot.speaker}** ({shot.dialogue_lang}): \"{shot.dialogue_tts}\"",
                    f"- Caption: \"{shot.dialogue_caption}\" ({shot.words} words, counted by code)",
                    f"- Delivery: {shot.delivery}"]
        if shot.headline:
            out.append(f"- Headline: {shot.headline}")
        out.append(f"- Keyframe prompt (Nano Banana): {keyframe_request(shot, look, brief, refs)[0]}")
        if shot.route != "static":
            out.append(f"- Motion prompt (Veo): {motion_prompt(shot, look, brief)}")
    # Fields may already end with a full stop; a real ellipsis ("...") is left alone.
    text = re.sub(r"(?<!\.)\.\.(?!\.)", ".", "\n".join(out))
    run.path("storyboard.md").write_text(text + "\n", "utf-8")


def write_decision_log_md(run: Run) -> None:
    """Readable copy of decision_log.jsonl, for the sample deliverables."""
    lines = ["# Decision log", "", "| Step | Choice | Reason | Cost |", "| --- | --- | --- | --- |"]
    for raw in run.path("decision_log.jsonl").read_text("utf-8").splitlines():
        e = json.loads(raw)
        lines.append(f"| {e['step']} | {e['choice']} | {e['reason']} | ${e['cost']:.3f} |")
    run.path("decision_log.md").write_text("\n".join(lines) + "\n", "utf-8")
