# sparkBoard: Ad Creative Generation System

Pipeline that turns a brand brief into checked ad creatives (images and videos).
Owner: Tarun. Build plan: docs/private/04_BUILD_PLAN.md (wins over docs/private/01 where they differ).

## Start of every session (always do this first)

1. Read this file, docs/PROMPTING.md, and docs/private/*.md (the build plan, decisions, brief and budget; not in the public repo).
2. Check `git log --oneline -15` and the code to see what's already built.
3. Reply in under 15 short lines: where we are, the next phase, and anything in the plan you'd improve after a fresh deep check (search the web for current best practices, model and API changes, and known issues). Say why for each suggestion.
4. Wait for Tarun's OK before building.

## Strict rules: keys, cost, safety

- Budget is approx $10 per key (Kie AI, OpenRouter, ElevenLabs), shared with every task.
- No paid API call without telling Tarun the expected cost and getting his clear OK.
- Dry-run / mock providers are the default. Real calls need `--live` and a cost cap.
- Every paid call goes through `ledger.py`, which records cost and refuses to run past the cap. Test on one item first, then scale.
- Keys only in `.env` (gitignored). Never print, log, commit or paste them anywhere.
- Never commit `docs/private/` (senior's emails, account details).
- Don't use any Google, VARWENT or Anuj-related plugins, MCP servers or connectors unless Tarun permits it. Never control his computer outside this folder.
- Any text Tarun will send (emails, messages): run it through the humanizer skill first.

## Storage rules

- Everything stays inside this repo folder. Use the `.venv` here; never install anything globally (no global pip, no system Python changes).
- uv's cache and Python install live in the repo: always set `UV_CACHE_DIR=.uv/cache` and `UV_PYTHON_INSTALL_DIR=.uv/python`. `.uv/` is gitignored, so deleting this folder removes everything.
- Ask Tarun before any download over 100 MB (torch, ML models). For heavy checks, prefer API-based checks (Gemini vision) over big local models; if something heavy is truly needed, tell him the size and options first, including a cloud environment.
- Generated media goes only in `runs/` (gitignored). `python -m adgen clean` deletes old runs and temp files.
- At the end of each phase, report disk space used by `.venv`, `.uv` and `runs/`.

## How to talk to Tarun

Easy English, short clean points, answer first. Plan big work first and wait for OK; just do small clear tasks.

## Code rules

- Python 3.12, ffmpeg, Typer CLI, Pydantic, one small Streamlit app. Simple, clear code (code clarity is graded).
- Each pipeline step writes JSON to `runs/<run_id>/` and is skipped on re-run if its output exists. Never overwrite a raw take.
- Model calls only through `adgen/providers/` (kie.py, openrouter.py, elevenlabs.py, mock.py).
- Kie: HTTP 200 even on failure, so check `code`. Save the task ID before polling; never resubmit on a poll timeout. Veo: always `enable_translation: false`.
- ffmpeg: normalize every clip to 1080x1920, 24 fps, yuv420p, 48 kHz before joining; one master audio track; no `-shortest`.
- Commit after each phase with a clear message.

## Layout

- `adgen/` pipeline steps, schemas, providers, editor, qa, ledger
- `playbooks/` category looks (YAML)
- `briefs/` sample briefs
- `assets/fonts/` caption and static fonts
- `tests/` pytest (no paid calls)
- `runs/` outputs (gitignored)
- `models/` local face check models (gitignored; `python -m adgen fetch-face-model`)
- `samples/` final samples, storyboards, decision logs
- `docs/` prompting rules and diagrams; `docs/private/` plan, brief, budget (gitignored)

## Commands

- Setup (PowerShell): `$env:UV_CACHE_DIR=".uv/cache"; $env:UV_PYTHON_INSTALL_DIR=".uv/python"`, then `uv venv --python 3.12 .venv`, then `uv pip install -r requirements.txt`, then `.venv\Scripts\activate`
- Clean: `python -m adgen clean --older-than-days 7` (use `0` for all dry runs; paid runs are kept unless `--include-paid`)
- Dry run: `python -m adgen run briefs/skincare.json --dry-run --auto-approve`
- Tests: `pytest -q`
