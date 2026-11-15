"""Pydantic models for every JSON file a run writes (one model per pipeline step)."""
from typing import Literal

from pydantic import BaseModel, model_validator

Route = Literal["veo_talk", "veo_broll", "avatar_talk", "vo_only", "static"]
TALK_ROUTES = ("veo_talk", "avatar_talk")
# About 15 words in 6 s. Longer lines get their last word cut off by the video model.
MAX_WORDS_PER_SECOND = 2.5


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
    product_url: str | None = None
    refs: Refs | None = None


class Insights(BaseModel):
    pains: list[str]
    desires: list[str]
    objections: list[str]
    proof_points: list[str]


class Concept(BaseModel):
    id: str
    title: str
    hook: str
    insight: str  # the customer insight this concept is built on
    score: float  # from the critic pass, 0-10


class Concepts(BaseModel):
    concepts: list[Concept]
    winner_id: str
    reason: str

    @model_validator(mode="after")
    def winner_exists(self):
        if self.winner_id not in {c.id for c in self.concepts}:
            raise ValueError(f"winner_id {self.winner_id!r} is not one of the concepts")
        return self

    @property
    def winner(self) -> Concept:
        return next(c for c in self.concepts if c.id == self.winner_id)


class Choice(BaseModel):
    value: str
    reason: str


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


class Character(BaseModel):
    name: str
    description: str
    outfit: str
    voice: str


class Shot(BaseModel):
    id: str
    purpose: str
    duration_s: int
    shot_type: str
    angle: str
    framing: str
    character: str | None = None
    speaker: str | None = None
    expression: str = ""
    action: str
    lighting: str
    location: str
    product_visible: bool = False
    dialogue_tts: str = ""      # what the voice says (Hindi words in Devanagari)
    dialogue_caption: str = ""  # same line in Roman script, for captions
    camera_move: str = ""
    audio_notes: str = "room tone only, no music"
    route: Route

    @model_validator(mode="after")
    def dialogue_fits(self):
        if self.route in TALK_ROUTES and not (self.speaker and self.dialogue_tts):
            raise ValueError(f"{self.id}: talking shots need a speaker and dialogue")
        words = len(self.dialogue_caption.split())
        if words > MAX_WORDS_PER_SECOND * self.duration_s:
            raise ValueError(f"{self.id}: {words} words is too many for {self.duration_s} s")
        return self


class Storyboard(BaseModel):
    title: str
    characters: list[Character]
    shots: list[Shot]

    @model_validator(mode="after")
    def shots_are_consistent(self):
        if self.shots[0].purpose != "hook":
            raise ValueError("the first shot must be the hook")
        names = {c.name for c in self.characters}
        for shot in self.shots:
            for who in (shot.character, shot.speaker):
                if who and who not in names:
                    raise ValueError(f"{shot.id}: unknown character {who!r}")
        return self


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
    status: Literal["rendered", "not_rendered"]
    files: list[str] = []
    note: str = ""


class Check(BaseModel):
    name: str
    passed: bool
    detail: str = ""


class QAReport(BaseModel):
    passed: bool
    checks: list[Check]
