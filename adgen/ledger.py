"""Cost ledger: every paid call is checked against the cap first, then recorded."""
import json
from pathlib import Path

# Hard caps per sample, in USD, one per API key (docs/04_BUILD_PLAN.md section 11).
CAPS = {"kie": 3.00, "elevenlabs": 0.50, "openrouter": 1.00}

# Approx prices in USD for the mock provider (docs/04_BUILD_PLAN.md section 3).
# Live OpenRouter calls do not use these: they read real prices and real costs from the API.
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


def has_real_spend(run_dir: Path) -> bool:
    """True if the run's ledger has any real (not mock) charge."""
    ledger = run_dir / "ledger.jsonl"
    return ledger.exists() and '"mock": false' in ledger.read_text("utf-8")


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

    def check(self, key: str, worst_cost: float) -> None:
        """Call BEFORE a paid call, with the most it could cost. Raises if that could pass the cap."""
        if self.spent(key) + worst_cost > self.caps[key] + 1e-9:
            raise BudgetExceeded(
                f"a call of up to ${worst_cost:.3f} could pass the {key} cap: "
                f"${self.spent(key):.3f} spent of ${self.caps[key]:.2f}"
            )

    def record(self, key: str, item: str, cost: float, mock: bool = False) -> None:
        """Call AFTER a paid call, with what it really cost."""
        entry = {"key": key, "item": item, "cost": cost, "mock": mock}
        self.entries.append(entry)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def charge(self, key: str, item: str, cost: float, mock: bool = False) -> None:
        """Check and record in one step, for calls with a fixed, known price."""
        self.check(key, cost)
        self.record(key, item, cost, mock)
