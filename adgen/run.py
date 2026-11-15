"""A run folder (runs/<run_id>/): step outputs as JSON, plus the decision log."""
import json
from pathlib import Path

from pydantic import BaseModel

RUNS_DIR = Path("runs")


class Run:
    def __init__(self, run_id: str, root: Path = RUNS_DIR):
        self.id = run_id
        self.dir = root / run_id
        self.dir.mkdir(parents=True, exist_ok=True)

    def path(self, name: str) -> Path:
        """Path of a file in the run folder; parent folders are created."""
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def rel(self, path: Path) -> str:
        """Path as stored in JSON: relative to the run folder, forward slashes."""
        return path.relative_to(self.dir).as_posix()

    def has(self, name: str) -> bool:
        return (self.dir / name).exists()

    def save(self, name: str, model: BaseModel) -> None:
        self.path(name).write_text(model.model_dump_json(indent=2), "utf-8")

    def load(self, name: str, cls: type[BaseModel]):
        return cls.model_validate_json((self.dir / name).read_text("utf-8"))

    def log(self, step: str, choice: str, reason: str, cost: float) -> None:
        """One line per decision in decision_log.jsonl."""
        entry = {"step": step, "choice": choice, "reason": reason, "cost": round(cost, 4)}
        with self.path("decision_log.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def write_decision_log_md(self) -> None:
        """Readable copy of the decision log, for the sample deliverables."""
        lines = ["# Decision log", "", "| Step | Choice | Reason | Cost |", "| --- | --- | --- | --- |"]
        for raw in self.path("decision_log.jsonl").read_text("utf-8").splitlines():
            e = json.loads(raw)
            lines.append(f"| {e['step']} | {e['choice']} | {e['reason']} | ${e['cost']:.3f} |")
        self.path("decision_log.md").write_text("\n".join(lines) + "\n", "utf-8")
