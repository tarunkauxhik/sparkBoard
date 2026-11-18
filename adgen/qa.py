"""Quality rules for generated images and clips: the pass/fail rules the checks use.
The face scores come from adgen/faces.py; OCR and the retry loop arrive in phase 5."""
from pydantic import BaseModel, Field

MAX_WORD_ERROR_RATE = 0.10
MIN_RUBRIC_SCORE = 3
KEYFRAME_TRIES = 3     # images are cheap ($0.03), so a failed face check gets two more tries
CLIP_TRIES = 2         # clips cost more; after two failed takes the shot is flagged, not retried
MAX_PITCH_GAP = 0.10   # a speaker's clips may differ in pitch by 10%; more sounds like another voice


PUNCTUATION = ".,!?…\"'“”‘’()[]:;—-।"


def _words(text: str) -> list[str]:
    """Lowercase words without punctuation. Split on spaces, so it also works for Devanagari
    (a regex word match would break Hindi words at their vowel signs). Apostrophes inside a word
    are dropped: "link's" and "links" sound the same, and a transcript may write either."""
    text = text.lower().replace("'", "").replace("’", "")
    return [word for word in (raw.strip(PUNCTUATION) for raw in text.split()) if word]


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


def last_word_heard(script: str, heard: str, other_script: str = "") -> bool:
    """True if the transcript ends on the script's last word (Veo sometimes cuts it off)."""
    want, other, got = _words(script), _words(other_script), _words(heard)
    endings = {want[-1]} | ({other[-1]} if other else set()) if want else set()
    return bool(got) and got[-1] in endings


def words_pass(script: str, heard: str, other_script: str = "") -> bool:
    return word_error_rate(script, heard, other_script) <= MAX_WORD_ERROR_RATE


# Face similarity limits from the smoke test (16 Nov 2026): 2 personas, 3 clips, 26 comparisons.
# Provisional: re-tune when there is more data. Scores come from adgen/faces.py (-1 to 1).
KEYFRAME_FACE_MIN = 0.45  # a keyframe against its character sheet. Measured 0.62 to 0.75 in soft daylight,
                          # but 0.49 to 0.52 for the right person under one hard light looking down; sheets
                          # of different people score 0.08 to 0.21, and face_passes also needs the face to
                          # be closer to its own person than to anyone else in the cast
CLIP_FACE_MIN = 0.50      # a clip frame against the shot's own keyframe, inside the spoken part
PERSONA_FACE_MAX = 0.45   # two different personas' sheets may not score above this (two that
                          # looked alike scored 0.66; re-make the newer sheet if they do)


def face_passes(own: float | None, others: list[float], minimum: float) -> bool:
    """A face passes if it is close enough to its own persona AND closer to it than to any
    other persona. The second test matters: two similar-looking personas scored up to 0.52
    against each other, so a fixed limit alone cannot tell them apart."""
    return own is not None and own >= minimum and all(own > other for other in others)


class LabelArea(BaseModel):
    """Where the blank label area is in a keyframe, in thousandths of the image width and height."""
    found: bool
    left: int = Field(ge=0, le=1000)
    top: int = Field(ge=0, le=1000)
    right: int = Field(ge=0, le=1000)
    bottom: int = Field(ge=0, le=1000)

    def box(self) -> tuple[float, float, float, float] | None:
        """The area as shares of the image size, or None if it was not found or makes no sense."""
        if not self.found or self.right <= self.left or self.bottom <= self.top:
            return None
        return self.left / 1000, self.top / 1000, self.right / 1000, self.bottom / 1000


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
