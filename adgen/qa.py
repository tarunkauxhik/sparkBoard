"""Quality rules for generated clips. The checks that need models (OCR, face match,
the Gemini call itself) arrive in phase 5; these are the pass/fail rules they will use."""
import re

from pydantic import BaseModel, Field

MAX_WORD_ERROR_RATE = 0.10
MIN_RUBRIC_SCORE = 3


def _words(text: str) -> list[str]:
    return re.findall(r"[\w']+", text.lower())


def word_error_rate(script: str, heard: str) -> float:
    """Share of script words the transcript got wrong (substituted, dropped or added).

    Compare like with like: both in Roman script, or both in mixed script."""
    want, got = _words(script), _words(heard)
    # Word-level edit distance, one row at a time.
    row = list(range(len(got) + 1))
    for i, expected in enumerate(want, 1):
        previous, row[0] = row[0], i
        for j, actual in enumerate(got, 1):
            previous, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, previous + (expected != actual))
    return row[-1] / max(len(want), 1)


def words_pass(script: str, heard: str) -> bool:
    return word_error_rate(script, heard) <= MAX_WORD_ERROR_RATE


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
