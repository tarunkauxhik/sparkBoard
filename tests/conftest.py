"""Shared test helpers. Nothing here makes a paid call."""
from pathlib import Path

import pytest

from adgen.ledger import Ledger
from adgen.pipeline import run_pipeline
from adgen.providers.mock import MockProvider
from adgen.run import Run

BRIEF = Path(__file__).parent.parent / "briefs/skincare.json"


def dry_run(root, auto_approve=True, provider_cls=MockProvider):
    run = Run("test", root=root)
    ledger = Ledger(run.path("ledger.jsonl"))
    finished = run_pipeline(BRIEF, run, provider_cls(ledger), ledger, auto_approve)
    return run, ledger, finished


@pytest.fixture(scope="session")
def done(tmp_path_factory):
    """One finished dry run, shared by the tests that only read it."""
    return dry_run(tmp_path_factory.mktemp("runs"))
