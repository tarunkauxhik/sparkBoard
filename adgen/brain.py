"""The LLM tasks: what each one is asked, and the JSON it must return.

One Task per LLM call. The provider builds the messages with build_messages();
the pipeline validates the reply against Task.schema and the code rules in rules.py.
"""
import json
from dataclasses import dataclass

from pydantic import BaseModel

from adgen.rules import GLOSSY_WORDS, HOOK_MAX_WORDS, OVERUSED_PHRASES, WARM_UP_WORDS
from adgen.schemas import (
    MIN_CAST_AGE, ConceptDrafts, ConceptReview, EditList, Insights, Look, Storyboard,
    StoryboardReview, max_words,
)

SYSTEM = (
    "You are the creative team behind short social video ads that feel like real people, "
    "not like ads. You write the way people actually talk. "
    "Reply with one JSON object only: no markdown fences, no text before or after it."
)

HOOK_TYPES = """Hook types (pick the one that fits, set hook_type and say why in hook_reason):
- first_use_reaction: we watch the first try happen, and the line reacts to it.
- drop_in_mid_scene: we land in the middle of a moment that is already going on.
- symptom_diagnosis: names the exact annoying symptom the viewer knows too well.
- contrarian: says the opposite of what this kind of ad usually says.
- third_person_proof: someone else noticed or said something about the speaker."""

STORYBOARD_RULES = f"""Hard rules (checked by code; a storyboard that breaks one is rejected):
- Routes: veo_talk = a cast member speaks on camera; veo_broll = silent footage;
  vo_only = silent footage under a narrator's line (it still needs speaker, dialogue_tts,
  dialogue_caption and dialogue_lang); static = a still ad with a headline (duration_s 0,
  no beats, no dialogue).
- The words decide the length. Code sets every spoken shot to the shortest duration that
  fits its line: up to {max_words(4)} words = 4 s, up to {max_words(6)} words = 6 s, up to
  {max_words(8)} words = 8 s. A line over {max_words(8)} words is rejected. Words are counted
  on dialogue_caption. (This leaves half a second of silence at each end of the line.)
- Those durations must add up to between length_s.min and length_s.max (see CONTEXT).
  So first write `plan`: count the words of each line one by one, note the duration that
  gives, and add up the total. A word is anything between two spaces, in any language:
  "Rohan ke 800 rupaye pending hain" is 6 words. Leave a margin, because miscounts are
  common: aim for 5 words or fewer in a 4 s line and 9 or fewer in a 6 s line, and aim for
  a total near length_s.min.
- Silent veo_broll shots last exactly 4, 6 or 8 seconds.
- One speaker per shot. In a veo_talk shot the speaker is the person on screen, the
  shot_type is exactly "medium close-up" and camera_move is exactly "static" or "light handheld".
- The first shot has purpose "hook". Its line is {HOOK_MAX_WORDS} words or fewer, opens on the
  tension itself and makes no product claim. It never starts with a warm-up word
  ({", ".join(WARM_UP_WORDS)}).
- In ugc and product_hero ads the product is visible (product_visible true) in shot 1.
- A ugc ad has at least one silent veo_broll shot (the product, hands or texture).
  A product_hero ad has at least one static shot.
- The last spoken shot has purpose "cta": a short, natural, soft call to action tied to
  the brief's goal, said the way a friend would ("it's linked below if you want to try it").
- Product claims, in lines and in headlines, come only from the brief's product_facts.
  Never add an ingredient, result, number, price, guarantee, refund or policy that is not listed.
- character and speaker are cast names from the look, nothing else. Adults only, no children.
- Every spoken shot has dialogue_tts, dialogue_caption and dialogue_lang, all non-empty.
  dialogue_tts is what the voice says: Hindi words in Devanagari, English words in Latin.
  dialogue_caption is the same line in Roman script only. dialogue_lang names the language
  ("Hinglish", "Indian English"); the accent comes from the persona.
- Silent shots (veo_broll, static) have empty dialogue fields.
- Every clip has 1 or 2 beats inside its duration (start_s, end_s). Each beat is one clear
  physical action plus an eye_line when a person is on screen ("looks into the lens",
  "looks at riya off-left"). Never an emotion on its own ("feels relieved").
- No exclamation marks. Never use these phrases: {", ".join(OVERUSED_PHRASES)}.
- Never write these words anywhere: {", ".join(GLOSSY_WORDS)}.

Craft rules:
- Dialogue sounds like one friend talking to another, in that persona's speech habits, pace
  and energy: contractions, short sentences, specific details. Allow one small filler or
  self-correction in the whole ad, no more. No slogans, no feature lists, no superlatives.
- No testimonial set-up to camera ("so I've been using...") and no forced enthusiasm.
- first_frame describes the still moment the shot opens on. Keep hand actions simple: the
  product is held plainly or rests on a surface.
- Every shot is a separate clip generated from its own still image. Never carry one
  movement across a cut ("mid-application", "continues to..."): open each shot on a settled pose.
- Avoid shots that only work if a tiny facial expression lands exactly; show it with an action.
- lighting names one real light source. audio_notes names the room tone of the place.
- Reuse the same location and lighting words in every shot that shares a place.
- On lines voiced by TTS (vo_only) you may add at most one audio tag such as [sighs] to
  dialogue_tts, and "..." for a pause. Never put tags in dialogue_caption."""


@dataclass
class Task:
    schema: type[BaseModel]
    max_tokens: int
    temperature: float
    instructions: str
    reasoning: str = "low"  # thinking effort; the storyboard tasks need more, to count words


TASKS = {
    "insights": Task(Insights, 2000, 0.5, (
        "Build the insight bank for this brief: the audience's pains, desires and objections "
        "about this kind of product, and the proof points that would answer them. "
        "Write each one the way a real customer would say it, 4 to 6 per list. "
        "Proof points may only restate the brief's product_facts: never invent ingredients, "
        "test results, prices, guarantees or policies.")),
    "concepts": Task(ConceptDrafts, 3000, 0.9, (
        "Propose exactly 5 ad concepts for the brief's format and platform, ids c1 to c5. "
        "Each one is built on a different insight and takes a clearly different angle. "
        "The hook is the first spoken line or first image and must earn attention in 2 seconds. "
        f"Avoid overused hooks such as: {', '.join(OVERUSED_PHRASES)}. "
        "Keep every concept shootable with 1 or 2 adults, simple actions and one location. "
        "Use only the brief's product_facts for product claims.")),
    "concept_critic": Task(ConceptReview, 2500, 0.3, (
        "You are a tough creative director. Score every concept from 1 to 10 on: hook, "
        "brief_fit, platform_fit, feasibility (can AI video models make it look real: few "
        "people, simple hands, no crowds, no on-screen text) and distinctiveness. "
        "Use the full range; generic concepts score low. Do not rewrite or improve the "
        "concepts. Return one review per concept id with a one or two sentence note.")),
    "look": Task(Look, 3000, 0.3, (
        "Decide the look of the ad for the winning concept. Start from the category playbook "
        "and adapt each field to this brand and concept; give the reason for every choice. "
        "lens names a real lens with its focal length and f-stop; light names one real light "
        f"source. Never write these words: {', '.join(GLOSSY_WORDS)}.\n"
        "Then define the cast as personas: fictional people with a short first name in "
        f"lowercase, age {MIN_CAST_AGE} or older, a plain physical look (never a likeness of a "
        "real or famous person), one outfit worn in every shot, a voice, an accent, a speaking "
        "pace, an energy level and 2 or 3 speech habits (how this person actually talks: a "
        "pet phrase, trailing off, dry understatement). If the ad needs a narrator, add them "
        "to the cast too. Keep the cast as small as the concept allows.")),
    "storyboard": Task(Storyboard, 5000, 0.3, (
        "Write the storyboard and script for the winning concept, shot ids s01, s02, ...\n\n"
        + HOOK_TYPES + "\n\n" + STORYBOARD_RULES), reasoning="medium"),
    "storyboard_critic": Task(StoryboardReview, 6000, 0.3, (
        "You are a script editor. Review the storyboard draft, then return the full "
        "storyboard with your fixes applied, plus one note per issue you found.\n"
        "- Rewrite any line that sounds like ad copy or a script (kind: ad_like).\n"
        "- Flag and soften health or money claims that cannot be proven (kind: claim).\n"
        "- For each spoken shot add one line_checks entry listing every product claim the "
        "line makes, each with `fact`: the index, counting from 0, of the product_facts entry "
        "that backs it. If nothing backs a claim, rewrite the line without it (kind: claim) so "
        "that no unbacked claim is left in the storyboard you return.\n"
        "- Replace overused hooks and stock phrases; fix a hook that warms up before the "
        "tension (kind: overused_hook).\n"
        "- Flag shots that depend on a micro-expression landing exactly, and replace the "
        "direction with a physical action (kind: micro_expression).\n"
        "- Check the last spoken line is a soft, natural call to action tied to the goal.\n"
        "- Anything else worth fixing (kind: other).\n"
        "Keep what already works; do not rewrite for the sake of it. If nothing needs "
        "changing, return the storyboard unchanged with an empty notes list. "
        "The returned storyboard must still follow every rule below.\n\n"
        + HOOK_TYPES + "\n\n" + STORYBOARD_RULES), reasoning="medium"),
    # Used from phase 5, once there are real clips and transcripts to cut.
    "edit_list": Task(EditList, 3000, 0.3, (
        "Write the edit list: the clips in order with in and out points and a reason for "
        "each cut, and the end card line.")),
}


def build_messages(task: str, ctx: dict, feedback: str = "") -> tuple[str, str]:
    """(system, user) messages for one task. `feedback` holds the errors of a rejected try."""
    spec = TASKS[task]
    user = "\n\n".join([
        f"TASK\n{spec.instructions}",
        f"CONTEXT\n{json.dumps(ctx, ensure_ascii=False, indent=1)}",
        f"JSON SCHEMA OF YOUR REPLY\n{json.dumps(spec.schema.model_json_schema())}",
    ])
    if feedback:
        user += (f"\n\nYOUR LAST REPLY WAS REJECTED for the problems below. Fix them without "
                 f"breaking any other rule, then check every rule once more before replying:\n{feedback}")
    return SYSTEM, user
