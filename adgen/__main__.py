"""Command line: `python -m adgen run <brief>` and `python -m adgen clean`."""
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

import typer
from dotenv import load_dotenv

from adgen.ledger import CAPS, Ledger, has_real_spend
from adgen.pipeline import run_pipeline
from adgen.providers.elevenlabs import ElevenLabs
from adgen.providers.kie import Kie
from adgen.providers.mock import MockProvider
from adgen.providers.openrouter import OpenRouter
from adgen.run import RUNS_DIR, Run
from adgen.smoke import STEPS

app = typer.Typer(add_completion=False, help="sparkBoard: brand brief in, checked ad creatives out.")


@app.command()
def run(
    brief: Path = typer.Argument(..., exists=True, help="Brief JSON, e.g. briefs/skincare.json"),
    live: bool = typer.Option(False, "--live/--dry-run", help="Real paid calls. Dry run is the default."),
    cap_openrouter: float = typer.Option(None, help="Hard cap in USD for OpenRouter. Required with --live."),
    auto_approve: bool = typer.Option(False, help="Skip the storyboard approval stop."),
    run_id: str = typer.Option(None, help="Resume this run instead of starting a new one."),
):
    """Run the pipeline. Steps that already have output are skipped."""
    if live and cap_openrouter is None:
        typer.echo("--live needs a cost cap, e.g. --cap-openrouter 0.50")
        raise typer.Exit(1)
    if live and auto_approve:
        typer.echo("Live image and video providers are not built yet (phase 5). "
                   "Run --live without --auto-approve: it stops at the storyboard.")
        raise typer.Exit(1)
    current = Run(run_id or f"{brief.stem}-{datetime.now():%Y%m%d-%H%M%S}")
    typer.echo(f"Run {current.id} ({'LIVE, real paid calls' if live else 'dry run, mock providers'})")
    if live:
        load_dotenv()
        ledger = Ledger(current.path("ledger.jsonl"), {**CAPS, "openrouter": cap_openrouter})
        provider = OpenRouter(ledger, current.dir / "llm", os.environ["OPENROUTER_API_KEY"])
    else:
        ledger = Ledger(current.path("ledger.jsonl"))
        provider = MockProvider(ledger)
    try:
        finished = run_pipeline(brief, current, provider, ledger, auto_approve)
        typer.echo(f"\n{'Finished' if finished else 'Stopped for approval'}: {current.dir}")
    finally:  # always say what was spent, also when a step failed
        typer.echo(f"{'Spent' if live else 'Projected cost of a live run'}: ${ledger.total():.3f} ("
                   + ", ".join(f"{key} ${ledger.spent(key):.3f} of {cap:.2f}" for key, cap in ledger.caps.items())
                   + ")")


@app.command()
def clean(
    older_than_days: int = typer.Option(7, help="Delete runs older than this. 0 deletes all dry runs."),
    include_paid: bool = typer.Option(False, help="Also delete runs that cost real money."),
):
    """Delete old run folders and temp files (pytest and Python caches).

    Runs that cost real money are kept unless --include-paid is given.
    """
    cutoff = time.time() - older_than_days * 86400
    old_runs = [d for d in RUNS_DIR.glob("*") if d.is_dir() and d.stat().st_mtime <= cutoff]
    kept = [d for d in old_runs if has_real_spend(d) and not include_paid]
    old_runs = [d for d in old_runs if d not in kept]
    caches = [d for d in Path(".").rglob("*") if d.name in ("__pycache__", ".pytest_cache")
              and d.is_dir() and not {".venv", ".uv", ".git"} & set(d.parts)]
    for folder in old_runs + caches:
        shutil.rmtree(folder)
    typer.echo(f"Deleted {len(old_runs)} run(s) and {len(caches)} cache folder(s). "
               f"Kept {len(kept)} paid run(s).")


@app.command()
def smoke(
    step: str = typer.Argument(..., help="Which step to run: " + ", ".join(STEPS)),
    cap_kie: float = typer.Option(..., help="Hard cap in USD for Kie across the whole smoke folder."),
    cap_elevenlabs: float = typer.Option(0.0, help="Hard cap in USD for ElevenLabs across the smoke folder."),
    folder: Path = typer.Option(None, help="Output folder. Default: runs/smoke-<today>."),
):
    """Run one step of the paid smoke test. Real calls: each step needs Tarun's OK first."""
    if step not in STEPS:
        typer.echo(f"Unknown step {step!r}. Steps: {', '.join(STEPS)}")
        raise typer.Exit(1)
    load_dotenv()
    folder = folder or RUNS_DIR / f"smoke-{datetime.now():%Y%m%d}"
    folder.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(folder / "ledger.jsonl", {**CAPS, "kie": cap_kie, "elevenlabs": cap_elevenlabs})
    typer.echo(f"Smoke step {step} in {folder} (LIVE)")
    try:
        STEPS[step](Kie(ledger, folder / "tasks", os.environ["KIE_API_KEY"]),
                    ElevenLabs(ledger, os.environ["ELEVENLABS_API_KEY"]), folder)
    finally:  # always say what was spent, also when a task failed
        typer.echo(f"Spent in this folder: Kie ${ledger.spent('kie'):.3f} of {cap_kie:.2f}, "
                   f"ElevenLabs ${ledger.spent('elevenlabs'):.4f} of {cap_elevenlabs:.2f}")


@app.command()
def save_sample(run_id: str, name: str):
    """Copy a reviewed run's JSON and markdown files into samples/<name>/, ready to commit.

    Media and LLM call logs stay in runs/ (gitignored).
    """
    source, target = RUNS_DIR / run_id, Path("samples") / name
    if not source.is_dir():
        typer.echo(f"No such run: {source}")
        raise typer.Exit(1)
    target.mkdir(parents=True, exist_ok=True)
    files = [f for f in source.iterdir() if f.suffix in (".json", ".jsonl", ".md")]
    for file in files:
        shutil.copyfile(file, target / file.name)
    typer.echo(f"Copied {len(files)} files to {target}")


if __name__ == "__main__":
    app()
