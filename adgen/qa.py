"""Quality rules for generated clips. The checks that need models (OCR, face match,
the Gemini call itself) arrive in phase 5; these are the pass/fail rules they will use."""
from pydantic import BaseModel, Field

MAX_WORD_ERROR_RATE = 0.10
MIN_RUBRIC_SCORE = 3


PUNCTUATION = ".,!?…\"'“”‘’()[]:;—-।"


def _words(text: str) -> list[str]:
    """Lowercase words without punctuation. Split on spaces, so it also works for Devanagari
    (a regex word match would break Hindi words at their vowel signs)."""
    return [word for word in (raw.strip(PUNCTUATION) for raw in text.lower().split()) if word]


def word_error_rate(script: str, heard: str, other_script: str = "") -> float:
    """Share of script words the transcript got wrong (substituted, dropped or added).

    `other_script` is the same line in its other writing (the Roman caption and the
    mixed-script voice line). A transcript writes each Hindi word in either script, so a
    heard word is right if it matches the word at that place in either writing."""
    want, other, got = _words(script), _words(other_script), _words(heard)
    accepted = [{word, other[i]} if len(other) == len(want) else {word} for i, word in enumerate(want)]
    # Word-level edit distance, one row at a time.
    row = list(range(len(got) + 1))
    for i, expected in enumerate(accepted, 1):
        previous, row[0] = row[0], i
        for j, actual in enumerate(got, 1):
            previous, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, previous + (actual not in expected))
    return row[-1] / max(len(want), 1)


def words_pass(script: str, heard: str, other_script: str = "") -> bool:
    return word_error_rate(script, heard, other_script) <= MAX_WORD_ERROR_RATE


class FaceCheck(BaseModel):
    """Gemini's answer to: is the person in this frame the person on the character sheet?"""
    same_person: bool
    score: int = Field(ge=1, le=5)  # 5 = clearly the same person, 3 = similar with differences, 1 = different
    judgement: str                  # what matches and what differs, in one or two sentences


class ClipScores(BaseModel):
    """Gemini's rubric for one clip: 1 (unusable) to 5 (looks real)."""
    hands: int = Field(ge=1, le=5)
    label: int = Field(ge=1, le=5)          # product shape and label match the packshot
    lip_sync: int = Field(ge=1, le=5)
    ai_look: int = Field(ge=1, le=5)        # 5 = no glossy, waxy or over-smooth "AI look"
    hook_strength: int = Field(ge=1, le=5)  # scored on the first shot only
    notes: str = ""

    def needs_reroll(self) -> bool:
        scores = (self.hands, self.label, self.lip_sync, self.ai_look, self.hook_strength)
        return min(scores) < MIN_RUBRIC_SCORE
