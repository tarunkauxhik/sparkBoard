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
SPEAKING_CAMERA = ("static", "light handheld")     # the only camera moves for on-camera speech
MAX_WORDS_PER_SECOND = 2.2
EDGE_SILENCE_S = 0.5  # silence at the start and end of a spoken shot, so no word gets cut off
MIN_CAST_AGE = 25
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
# Not plain "looks like": that also matched "looks like someone with sensitive skin".
LIKENESS = re.compile(r"resembl|lookalike|celebrit|famous|actor|actress|film star|bollywood|hollywood",
                      re.IGNORECASE)


def max_words(duration_s: int) -> int:
    """Most words a spoken shot of this length may carry."""
    return int(MAX_WORDS_PER_SECOND * (duration_s - 2 * EDGE_SILENCE_S))


class Refs(BaseModel):
    """Reference images, as paths. Given in the brief or generated in step 5."""
    characters: dict[str, str] = {}
    product: list[str] = []
    location: str = ""


class AppRow(BaseModel):
    name: str
    amount: str  # as shown on screen, e.g. "Rs 800"


class AppScreen(BaseModel):
    """For app products: the one screen shown in the ad. Code draws it (statics.app_screen),
    so its text is exact, and the drawing is the product reference instead of a packshot."""
    title: str            # e.g. "Flat 4B"
    rows: list[AppRow]    # e.g. who owes what
    button: str           # e.g. "Pay now"
    color: str            # the brand colour as hex, e.g. "#16c172"


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
    app_screen: AppScreen | None = None  # set when the product is an app
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
    """A persona: a fictional adult. Shots and references refer to the cast by name only."""
    name: str
    age: int
    on_screen: bool = True  # false for a narrator who is only heard
    look: str = ""    # skin tone, face, hair, build: plain description, no real person
    outfit: str = ""  # worn in every shot
    voice: str   # how the voice sounds, e.g. "warm, mid-pitch"
    accent: str  # e.g. "neutral urban Indian English"
    pace: str    # e.g. "unhurried, with small pauses"
    energy: str  # e.g. "low-key and dry"
    speech_habits: list[str] = Field(min_length=2, max_length=3)  # e.g. "trails off with 'so, yeah'"

    @property
    def persona(self) -> str:
        """The exact words used for this person in every image and video prompt."""
        return f"{self.look.rstrip('.')}, age {self.age}, wearing {self.outfit.rstrip('.').lower()}"

    @model_validator(mode="after")
    def is_a_fictional_adult(self):
        if self.age < MIN_CAST_AGE:
            raise ValueError(f"{self.name}: cast must be {MIN_CAST_AGE} or older, got {self.age}")
        if LIKENESS.search(self.look):
            raise ValueError(f"{self.name}: describe the look plainly, never by likeness to a real person")
        if self.on_screen and not (self.look and self.outfit):
            raise ValueError(f"{self.name}: an on-screen persona needs a look and an outfit")
        return self


class Look(BaseModel):
    """The creative look. Every choice carries its reason for the decision log."""
    mood: Choice
    tone: Choice
    setting: Choice
    camera: Choice
    lens: Choice
    light: Choice
    palette: Choice  # the colours of the scene itself, without the product
    pacing: Choice
    brand_accent: str = ""  # the brand colour and where it shows; only used in shots with the product
    cast: list[CastMember]

    def choices(self) -> list[tuple[str, Choice]]:
        """The look fields that are a choice with a reason (not the cast, not the accent)."""
        return [(name, value) for name, value in self if isinstance(value, Choice)]


class Beat(BaseModel):
    """One timed moment inside a shot: a physical action and where the eyes look."""
    start_s: float
    end_s: float
    action: str         # one clear physical action, never an emotion alone
    eye_line: str = Field(default="", description="Where the eyes look, e.g. 'looks into the lens'. "
                          "Required in every beat of a shot that has a character on screen.")


class Shot(BaseModel):
    id: str
    purpose: str  # hook, problem, product, proof, payoff, cta ...
    duration_s: int
    shot_type: str
    angle: str
    framing: str
    character: str | None = None  # cast name of the person on screen
    speaker: str | None = None    # cast name of the person speaking
    face_visible: bool = True     # false when only hands or the back of a person show
    first_frame: str  # the still moment the shot starts on (becomes the keyframe)
    beats: list[Beat] = Field(default=[], max_length=2)  # what happens after the first frame
    setting: str   # only the part of the location and the objects visible in this shot
    lens: str      # one lens for this shot, with focal length and f-stop
    lighting: str  # one real light source
    location: str  # short name of the place, the same in every shot filmed there
    product_visible: bool = False
    blank_label_text: str = ""  # printed text (a date, a price) that code adds later; the
                                # keyframe leaves that label area blank
    dialogue_tts: str = ""      # the spoken line; Hindi words in Devanagari, English in Latin.
                                # May hold one ElevenLabs audio tag such as [sighs] on TTS routes.
    dialogue_caption: str = ""  # the same line in Roman script only, for captions and word counts
    dialogue_lang: str = ""     # language of this line, e.g. "Hinglish"; the accent comes from the persona
    delivery: str = ""          # how this one line is said in this shot, e.g. "quiet, half to herself"
    headline: str = ""          # static shots only: the text on the static ad
    camera_move: str = ""
    audio_notes: str = "quiet room tone"  # the ambient sound of the place
    route: Route

    @model_validator(mode="after")
    def follows_shot_rules(self):
        if self.route == "veo_broll" and self.duration_s not in (4, 6, 8):
            raise ValueError(f"{self.id}: silent Veo shots must be 4, 6 or 8 s, got {self.duration_s}")
        if self.route == "static" and not self.headline:
            raise ValueError(f"{self.id}: static shots need a headline")
        if self.route in ON_CAMERA and self.shot_type.lower() != "medium close-up":
            raise ValueError(f"{self.id}: on-camera speaking shots must be 'medium close-up'")
        if self.route in ON_CAMERA and self.character != self.speaker:
            raise ValueError(f"{self.id}: in an on-camera speaking shot the speaker is the person on screen")
        if self.route in ON_CAMERA and self.camera_move.lower() not in SPEAKING_CAMERA:
            raise ValueError(f"{self.id}: speaking shots need camera_move 'static' or 'light handheld'")
        if self.lens.lower().count("mm") > 1 or " or " in self.lens.lower():
            raise ValueError(f"{self.id}: name exactly one lens for this shot, got {self.lens!r}")
        if self.route in SPOKEN:
            if not (self.speaker and self.dialogue_tts and self.dialogue_caption
                    and self.dialogue_lang and self.delivery):
                raise ValueError(f"{self.id}: spoken shots need speaker, dialogue_tts, "
                                 "dialogue_caption, dialogue_lang and delivery")
            if "!" in self.dialogue_caption + self.dialogue_tts:
                raise ValueError(f"{self.id}: no exclamation marks, they read as forced enthusiasm")
            # The model's own word count is never trusted: code counts the caption and sets
            # the length to the shortest one that fits, moving the beats with it.
            fits = [seconds for seconds in (4, 6, 8) if self.words <= max_words(seconds)]
            if not fits:
                raise ValueError(f"{self.id}: {self.words} words is too long for one shot "
                                 f"(max {max_words(8)}); shorten the line or split the shot")
            if self.duration_s != fits[0]:
                scale = fits[0] / max(self.duration_s, 1)
                for beat in self.beats:
                    beat.start_s = round(beat.start_s * scale, 1)
                    beat.end_s = min(round(beat.end_s * scale, 1), fits[0])
                self.duration_s = fits[0]
        elif self.dialogue_tts or self.dialogue_caption:
            raise ValueError(f"{self.id}: route {self.route} is silent, remove the dialogue")
        if DEVANAGARI.search(self.dialogue_caption) or "[" in self.dialogue_caption:
            raise ValueError(f"{self.id}: dialogue_caption must be Roman script with no audio tags")
        if self.dialogue_tts.count("[") > 1:
            raise ValueError(f"{self.id}: at most one audio tag per line")
        if "hin" in self.dialogue_lang.lower() and not DEVANAGARI.search(self.dialogue_tts):
            raise ValueError(f"{self.id}: a {self.dialogue_lang} line needs its Hindi words in Devanagari in "
                             "dialogue_tts (a line with no Hindi words has dialogue_lang 'English')")
        if self.route != "static":
            if not self.beats:
                raise ValueError(f"{self.id}: every clip needs 1 or 2 beats")
            for beat in self.beats:
                if not 0 <= beat.start_s < beat.end_s <= self.duration_s:
                    raise ValueError(f"{self.id}: beat {beat.start_s}-{beat.end_s} s is outside "
                                     f"the shot (0-{self.duration_s} s)")
                if self.character and self.face_visible and not beat.eye_line:
                    raise ValueError(f"{self.id}: each beat needs an eye_line when a face is on screen")
        return self

    @property
    def words(self) -> int:
        """Words in the spoken line, counted by code on the Roman caption."""
        return len(self.dialogue_caption.split())


HookType = Literal["first_use_reaction", "drop_in_mid_scene", "symptom_diagnosis",
                   "contrarian", "third_person_proof"]


class Storyboard(BaseModel):
    title: str
    hook_type: HookType
    hook_reason: str  # why this hook type suits the audience and concept
    # Written first by the model so it does its sums before the shots; then replaced by
    # code with the real counts, because the model's counts are often wrong.
    plan: str = Field(description="Working notes on one line, written first: for each shot the word "
                                  "count of its line and its duration, then the total in seconds.")
    shots: list[Shot] = Field(min_length=1)
    end_card_line: str  # the one line under the brand name on the end card (drawn in code)

    @model_validator(mode="after")
    def starts_with_the_hook(self):
        if self.shots[0].purpose != "hook":
            raise ValueError("the first shot's purpose must be 'hook'")
        ids = [shot.id for shot in self.shots]
        if len(ids) != len(set(ids)):
            raise ValueError("shot ids must be unique")
        self.plan = self.counts
        return self

    @property
    def length_s(self) -> int:
        return sum(shot.duration_s for shot in self.shots if shot.route != "static")

    @property
    def counts(self) -> str:
        """The real word count and duration of every shot, and the total."""
        parts = [f"{shot.id} {shot.words} words = {shot.duration_s} s" if shot.route in SPOKEN
                 else f"{shot.id} silent = {shot.duration_s} s"
                 for shot in self.shots if shot.route != "static"]
        return "; ".join(parts) + f"; total {self.length_s} s"


class CriticNote(BaseModel):
    shot_id: str
    kind: Literal["ad_like", "claim", "overused_hook", "micro_expression", "other"]
    issue: str
    change: str  # what the critic changed, or "none" if only flagged


class Claim(BaseModel):
    claim: str               # a product claim, in the line's own words
    fact: int | None = None  # index (from 0) of the brief's product_facts entry that backs it


class LineCheck(BaseModel):
    """The critic's claim check for one piece of text the viewer hears or reads."""
    shot_id: str = Field(description="The shot id for a spoken line or a static headline; "
                                     "'end_card' for the end card line.")
    claims: list[Claim] = []  # empty if the text makes no product claim


class StoryboardReview(BaseModel):
    notes: list[CriticNote]
    line_checks: list[LineCheck]  # one per spoken line, per static headline, and one for the end card
    storyboard: Storyboard  # the full storyboard after the critic's rewrites


class Approval(BaseModel):
    approved: bool
    by: Literal["auto", "human"]


class Word(BaseModel):
    word: str
    start_s: float
    end_s: float


class KeyframeTake(BaseModel):
    shot_id: str
    take: int
    file: str
    face: float | None = None  # similarity to the character sheet; None if no face is meant to show
    passed: bool = True


class Keyframes(BaseModel):
    files: dict[str, str]           # shot id -> the chosen image
    takes: list[KeyframeTake] = []  # every try, with its check result


class Take(BaseModel):
    """One generated clip and what the checks found in it. Every take is kept."""
    shot_id: str
    take: int
    file: str
    task_id: str
    model: str
    words: list[Word] = []                # transcript word timings (spoken shots), in clip time
    voice_file: str = ""                  # vo_only: the narrator's TTS line, laid over the clip
    voice_start_s: float = 0.0            # vo_only: where in the clip the narrator's file starts
    word_error_rate: float | None = None
    face: float | None = None             # lowest similarity to the keyframe over the checked frames
    problems: list[str] = []              # why this take failed its checks; empty = passed

    @property
    def passed(self) -> bool:
        return not self.problems

    @property
    def made(self) -> bool:
        """False when the video service failed to make this take: there is no clip."""
        return not any(problem.startswith("generation failed") for problem in self.problems)


class Clips(BaseModel):
    takes: list[Take]

    def chosen(self) -> dict[str, Take]:
        """The take used for each shot: one that passed, else the made one with the fewest problems."""
        best = {}
        for take in self.takes:
            if not take.made:
                continue
            current = best.get(take.shot_id)
            if current is None or len(take.problems) < len(current.problems):
                best[take.shot_id] = take
        return best


class FixedClip(BaseModel):
    shot_id: str
    file: str
    words: list[Word] = []  # transcript word timings, used for trims and captions
    clicks_removed: list[tuple[float, float]] = []  # stray clicks or taps muted between words (seconds)


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
