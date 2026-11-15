"""Pydantic models for every JSON file a run writes (one model per pipeline step).

Rules about a single shot or cast member are checked here. Rules that need the
brief or the cast as well (total length, cast names) are in rules.py.
"""
import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Route = Literal["veo_talk", "veo_broll", "avatar_talk", "vo_only", "static"]
VEO_ROUTES = ("veo_talk", "veo_broll", "vo_only")  # clips made by Veo: only 4, 6 or 8 s
ON_CAMERA = ("veo_talk", "avatar_talk")            # the speaker is on screen, lip-synced
SPOKEN = ON_CAMERA + ("vo_only",)                  # shots that have a spoken line
MAX_WORDS_PER_SECOND = 2.2
EDGE_SILENCE_S = 0.5  # silence at the start and end of a spoken shot, so no word gets cut off
MIN_CAST_AGE = 25
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
LIKENESS = re.compile(r"looks? like|resembl|lookalike|celebrit|actor|actress", re.IGNORECASE)


def max_words(duration_s: int) -> int:
    """Most words a spoken shot of this length may carry."""
    return int(MAX_WORDS_PER_SECOND * (duration_s - 2 * EDGE_SILENCE_S))


class Refs(BaseModel):
    """Reference images, as paths. Given in the brief or generated in step 5."""
    characters: dict[str, str] = {}
    product: list[str] = []
    location: str = ""


class Brief(BaseModel):
    brand: str
    product: str
    category: str  # picks the playbook, e.g. "skincare"
    format: Literal["ugc", "role_play", "product_hero", "brand_story"]
    audience: str
    goal: str
    platform: str
    language: str
    # The only product claims an ad may make. Anything else (results, prices, refunds) is rejected.
    product_facts: list[str] = Field(min_length=1)
    target_length_s: int  # length of the shots together, without the end card
    product_url: str | None = None
    refs: Refs | None = None


class Insights(BaseModel):
    pains: list[str]
    desires: list[str]
    objections: list[str]
    proof_points: list[str]


class ConceptDraft(BaseModel):
    id: str
    title: str
    hook: str     # the first spoken line or first image
    insight: str  # the customer insight this concept is built on
    summary: str  # what happens, in two or three sentences


class ConceptDrafts(BaseModel):
    concepts: list[ConceptDraft] = Field(min_length=5, max_length=5)


class Scores(BaseModel):
    """Critic scores, 1 (weak) to 10 (strong)."""
    hook: int = Field(ge=1, le=10)
    brief_fit: int = Field(ge=1, le=10)
    platform_fit: int = Field(ge=1, le=10)
    feasibility: int = Field(ge=1, le=10)  # can today's AI video models make this look real?
    distinctiveness: int = Field(ge=1, le=10)

    @property
    def total(self) -> int:
        return self.hook + self.brief_fit + self.platform_fit + self.feasibility + self.distinctiveness


class ConceptScore(BaseModel):
    id: str
    scores: Scores
    note: str  # why these scores, in one or two sentences


class ConceptReview(BaseModel):
    reviews: list[ConceptScore]


class Concept(ConceptDraft):
    scores: Scores
    note: str


class Concepts(BaseModel):
    concepts: list[Concept]
    winner_id: str  # picked in code: the highest total score
    reason: str

    @property
    def winner(self) -> Concept:
        return next(c for c in self.concepts if c.id == self.winner_id)


class Choice(BaseModel):
    value: str
    reason: str


class CastMember(BaseModel):
    """A fictional adult. Shots and references refer to the cast by name only."""
    name: str
    age: int
    look: str    # face, hair, build: plain description, no real person
    outfit: str  # worn in every shot
    voice: str   # e.g. "warm, mid-pitch, Indian English"

    @model_validator(mode="after")
    def is_a_fictional_adult(self):
        if self.age < MIN_CAST_AGE:
            raise ValueError(f"{self.name}: cast must be {MIN_CAST_AGE} or older, got {self.age}")
        if LIKENESS.search(self.look):
            raise ValueError(f"{self.name}: describe the look plainly, never by likeness to a real person")
        return self


class Look(BaseModel):
    """The creative look. Every choice carries its reason for the decision log."""
    mood: Choice
    tone: Choice
    setting: Choice
    camera: Choice
    lens: Choice
    light: Choice
    palette: Choice
    pacing: Choice
    cast: list[CastMember]


class Shot(BaseModel):
    id: str
    purpose: str  # hook, problem, product, proof, payoff, cta ...
    duration_s: int
    shot_type: str
    angle: str
    framing: str
    character: str | None = None  # cast name of the person on screen
    speaker: str | None = None    # cast name of the person speaking
    expression: str = ""
    first_frame: str  # the still moment the shot starts on (becomes the keyframe)
    action: str       # what moves after the first frame
    lighting: str
    location: str
    product_visible: bool = False
    dialogue_tts: str = ""      # the spoken line; Hindi words in Devanagari, English in Latin
    dialogue_caption: str = ""  # the same line in Roman script only, for captions
    dialogue_lang: str = ""     # language and accent of this line, e.g. "Hinglish, Mumbai accent"
    headline: str = ""          # static shots only: the text on the static ad
    camera_move: str = ""
    audio_notes: str = "room tone only, no music"
    route: Route

    @model_validator(mode="after")
    def follows_shot_rules(self):
        if self.route in VEO_ROUTES and self.duration_s not in (4, 6, 8):
            raise ValueError(f"{self.id}: Veo shots must be 4, 6 or 8 s, got {self.duration_s}")
        if self.route == "static" and not self.headline:
            raise ValueError(f"{self.id}: static shots need a headline")
        if self.route in ON_CAMERA and self.shot_type.lower() != "medium close-up":
            raise ValueError(f"{self.id}: on-camera speaking shots must be 'medium close-up'")
        if self.route in SPOKEN:
            if not (self.speaker and self.dialogue_tts and self.dialogue_caption and self.dialogue_lang):
                raise ValueError(f"{self.id}: spoken shots need speaker, dialogue_tts, "
                                 "dialogue_caption and dialogue_lang")
            # LLMs miscount words, so code picks the length: the shortest one that fits the line.
            words = len(self.dialogue_caption.split())
            if words > max_words(self.duration_s):
                fits = [seconds for seconds in (4, 6, 8) if words <= max_words(seconds)]
                if not fits:
                    raise ValueError(f"{self.id}: {words} words is too long for one shot "
                                     f"(max {max_words(8)}); shorten the line or split the shot")
                self.duration_s = fits[0]
        elif self.dialogue_tts or self.dialogue_caption:
            raise ValueError(f"{self.id}: route {self.route} is silent, remove the dialogue")
        if DEVANAGARI.search(self.dialogue_caption):
            raise ValueError(f"{self.id}: dialogue_caption must be in Roman script")
        return self


class Storyboard(BaseModel):
    title: str
    # The model's working notes. Written before the shots, so it does its sums first.
    plan: str = Field(description="Working notes on one line, written first: for each shot the word "
                                  "count of its line and its duration, then the total in seconds.")
    shots: list[Shot] = Field(min_length=1)

    @model_validator(mode="after")
    def starts_with_the_hook(self):
        if self.shots[0].purpose != "hook":
            raise ValueError("the first shot's purpose must be 'hook'")
        ids = [shot.id for shot in self.shots]
        if len(ids) != len(set(ids)):
            raise ValueError("shot ids must be unique")
        return self


class CriticNote(BaseModel):
    shot_id: str
    kind: Literal["ad_like", "claim", "overused_hook", "other"]
    issue: str
    change: str  # what the critic changed, or "none" if only flagged


class LineCheck(BaseModel):
    """The critic's claim check for one spoken line."""
    shot_id: str
    claim: str = ""          # the product claim the line makes; empty if it makes none
    fact: int | None = None  # index (from 0) of the brief's product_facts entry that backs it


class StoryboardReview(BaseModel):
    notes: list[CriticNote]
    line_checks: list[LineCheck]  # one per spoken shot
    storyboard: Storyboard  # the full storyboard after the critic's rewrites


class Approval(BaseModel):
    approved: bool
    by: Literal["auto", "human"]


class Keyframes(BaseModel):
    files: dict[str, str]  # shot id -> image path


class Take(BaseModel):
    shot_id: str
    take: int
    file: str
    task_id: str
    model: str


class Clips(BaseModel):
    takes: list[Take]


class Word(BaseModel):
    word: str
    start_s: float
    end_s: float


class FixedClip(BaseModel):
    shot_id: str
    file: str
    words: list[Word] = []  # transcript word timings, used for trims and captions


class Audio(BaseModel):
    clips: list[FixedClip]


class Cut(BaseModel):
    shot_id: str
    file: str
    in_s: float
    out_s: float
    reason: str


class EndCard(BaseModel):
    line: str
    duration_s: float


class EditList(BaseModel):
    cuts: list[Cut]
    end_card: EndCard


class Render(BaseModel):
    files: list[str]  # the final video first, then any static ads


class Check(BaseModel):
    name: str
    passed: bool
    detail: str = ""


class QAReport(BaseModel):
    passed: bool
    checks: list[Check]
