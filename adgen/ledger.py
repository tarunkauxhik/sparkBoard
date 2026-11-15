"""Cost ledger: every paid call is recorded here first, and refused if it would pass the cap."""
import json
from pathlib import Path

# Hard caps per sample, in USD, one per API key (docs/04_BUILD_PLAN.md section 11).
CAPS = {"kie": 3.00, "elevenlabs": 0.50, "openrouter": 1.00}

# Approx prices in USD (docs/04_BUILD_PLAN.md section 3). Re-check before phase 4.
PRICES = {
    "sonnet_call": 0.05,
    "gemini_review": 0.01,
    "image": 0.025,
    "veo3_fast": 0.30,
    "veo3_lite": 0.15,
    "kling_avatar_per_s": 0.05,
    "voice_change_per_s": 0.002,  # approx $0.12 per minute
    "scribe_per_s": 0.0001,
}


class BudgetExceeded(RuntimeError):
    pass


class Ledger:
    """Append-only JSONL file, so a resumed run still counts what it already spent."""

    def __init__(self, path: Path, caps: dict[str, float] = CAPS):
        self.path = path
        self.caps = caps
        self.entries = []
        if path.exists():
            self.entries = [json.loads(line) for line in path.read_text("utf-8").splitlines()]

    def spent(self, key: str) -> float:
        return sum(e["cost"] for e in self.entries if e["key"] == key)

    def total(self) -> float:
        return sum(e["cost"] for e in self.entries)

    def charge(self, key: str, item: str, cost: float, mock: bool = False) -> None:
        """Call this BEFORE the paid call. Raises instead of letting spend pass the cap."""
        if self.spent(key) + cost > self.caps[key] + 1e-9:
            raise BudgetExceeded(
                f"{item} (${cost:.3f}) would pass the {key} cap: "
                f"${self.spent(key):.2f} spent of ${self.caps[key]:.2f}"
            )
        entry = {"key": key, "item": item, "cost": cost, "mock": mock}
        self.entries.append(entry)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
