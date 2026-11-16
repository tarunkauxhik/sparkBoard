"""Cast variety across samples: a new persona must not look like one used for another brand.

This checks the written description only, which is a first filter. The smoke test showed it
is not enough on its own: two personas with different wording still got near-identical
faces (0.66 on the face check). The real test is the face check on the finished character
sheets (adgen/faces.py, PERSONA_FACE_MAX in adgen/qa.py).

There is no age rule on purpose: an age gap between brands forced a cast of 42-year-olds
onto an ad for flatmates in their twenties. The brief's audience decides the age."""
import json
import re
from pathlib import Path

from adgen.ledger import has_real_spend
from adgen.schemas import Look

MAX_LOOK_SIMILARITY = 0.30  # share of look words two personas may have in common
FILLER = {"with", "and", "the", "her", "his", "their", "that", "from", "has", "have", "for",
          "woman", "man", "person", "face", "slightly", "light", "small", "few", "who", "wears"}


def _look_words(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z]+", text.lower()) if len(word) > 2 and word not in FILLER}


def look_similarity(a: str, b: str) -> float:
    """0 = nothing in common, 1 = the same words (Jaccard overlap of the look words)."""
    first, second = _look_words(a), _look_words(b)
    return len(first & second) / max(len(first | second), 1)


def used_personas(brand: str, runs_root: Path, samples_dir: Path = Path("samples")) -> list[dict]:
    """On-screen personas already cast for other brands: the newest look per brand,
    taken from saved samples and from paid runs (dry runs are placeholders and do not count)."""
    newest = {}  # brand -> (time, cast)
    folders = [d for d in samples_dir.glob("*") if d.is_dir()]
    folders += [d for d in runs_root.glob("*") if d.is_dir() and has_real_spend(d)]
    for folder in folders:
        brief_file, look_file = folder / "brief.json", folder / "look.json"
        if not (brief_file.exists() and look_file.exists()):
            continue
        other = json.loads(brief_file.read_text("utf-8"))["brand"]
        when = look_file.stat().st_mtime
        if other != brand and when > newest.get(other, (0, None))[0]:
            newest[other] = (when, json.loads(look_file.read_text("utf-8"))["cast"])
    return [{"brand": other, **{key: member.get(key) for key in ("name", "age", "look", "outfit", "voice", "speech_habits")}}
            for other, (_, cast) in sorted(newest.items()) for member in cast if member.get("on_screen", True)]


def casting_errors(look: Look, used: list[dict]) -> list[str]:
    """Reasons a new cast is too close to personas already used for other brands."""
    errors = []
    for member in look.cast:
        if not member.on_screen:
            continue
        for other in used:
            who = f"{other['name']} ({other['brand']})"
            if member.name == other["name"]:
                errors.append(f"{member.name}: the name is already used by {who}; pick another")
            overlap = look_similarity(member.look, other["look"])
            if overlap > MAX_LOOK_SIMILARITY:
                errors.append(f"{member.name}: the look is too close to {who} ({overlap:.0%} of the same "
                              "words); change the face shape, skin tone, hair, build and features")
    return errors


def other_sheets(brand: str, runs_root: Path) -> list[tuple[str, Path]]:
    """Character sheets already made for other brands, as (persona name, image path): from
    each other brand's newest paid run. New sheets are face-checked against these."""
    newest = {}  # brand -> (time, run folder)
    for folder in runs_root.glob("*"):
        brief_file, refs = folder / "brief.json", folder / "refs"
        if not (brief_file.exists() and refs.is_dir() and has_real_spend(folder)):
            continue
        other = json.loads(brief_file.read_text("utf-8"))["brand"]
        when = refs.stat().st_mtime
        if other != brand and when > newest.get(other, (0, None))[0]:
            newest[other] = (when, folder)
    return [(sheet.stem.removesuffix("_sheet"), sheet)
            for _, folder in newest.values() for sheet in sorted((folder / "refs").glob("*_sheet.png"))]
