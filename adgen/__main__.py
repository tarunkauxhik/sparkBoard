"""Command line: `python -m adgen run <brief>` and `python -m adgen clean`."""
import shutil
import time
from datetime import datetime
from pathlib import Path

import typer

from adgen.ledger import Ledger
from adgen.pipeline import run_pipeline
from adgen.providers.mock import MockProvider
from adgen.run import RUNS_DIR, Run

app = typer.Typer(add_completion=False, help="sparkBoard: brand brief in, checked ad creatives out.")


@app.command()
def run(
    brief: Path = typer.Argument(..., exists=True, help="Brief JSON, e.g. briefs/skincare.json"),
    live: bool = typer.Option(False, "--live/--dry-run", help="Real paid calls. Dry run is the default."),
    auto_approve: bool = typer.Option(False, help="Skip the storyboard approval stop."),
    run_id: str = typer.Option(None, help="Resume this run instead of starting a new one."),
):
    """Run the pipeline. Steps that already have output are skipped."""
    if live:
        typer.echo("Live providers are not built yet (phases 3-5). Use --dry-run.")
        raise typer.Exit(1)
    current = Run(run_id or f"{brief.stem}-{datetime.now():%Y%m%d-%H%M%S}")
    ledger = Ledger(current.path("ledger.jsonl"))
    typer.echo(f"Run {current.id} (dry run, mock providers)")
    finished = run_pipeline(brief, current, MockProvider(ledger), ledger, auto_approve)
    typer.echo(f"\n{'Finished' if finished else 'Stopped for approval'}: {current.dir}")
    typer.echo(f"Projected cost of a live run: ${ledger.total():.2f} "
               + ", ".join(f"{key} ${ledger.spent(key):.2f}/{cap:.2f}" for key, cap in ledger.caps.items()))


@app.command()
def clean(older_than_days: int = typer.Option(7, help="Delete runs older than this. 0 deletes all runs.")):
    """Delete old run folders and temp files (pytest and Python caches)."""
    cutoff = time.time() - older_than_days * 86400
    old_runs = [d for d in RUNS_DIR.glob("*") if d.is_dir() and d.stat().st_mtime <= cutoff]
    caches = [d for d in Path(".").rglob("*") if d.name in ("__pycache__", ".pytest_cache")
              and d.is_dir() and not {".venv", ".uv", ".git"} & set(d.parts)]
    for folder in old_runs + caches:
        shutil.rmtree(folder)
    typer.echo(f"Deleted {len(old_runs)} run(s) and {len(caches)} cache folder(s).")


if __name__ == "__main__":
    app()
