# sparkBoard

Turns a brand brief into checked ad creatives (images and videos) with one command.
Work in progress. The prompting and API rules the code follows are in [docs/PROMPTING.md](docs/PROMPTING.md).

## Quickstart (Windows PowerShell)

Needs [uv](https://docs.astral.sh/uv/) and ffmpeg. Everything installs inside this folder.

```powershell
$env:UV_CACHE_DIR=".uv/cache"; $env:UV_PYTHON_INSTALL_DIR=".uv/python"
uv venv --python 3.12 .venv
uv pip install -r requirements.txt
.venv\Scripts\activate
python -m adgen run briefs/skincare.json --dry-run --auto-approve
pytest -q
```

A dry run uses mock providers and costs $0. Outputs go to `runs/<run_id>/`.
A live run makes paid calls and needs a hard cost cap per service:
`python -m adgen run briefs/skincare.json --live --auto-approve --cap-kie 2 --cap-elevenlabs 0.3 --cap-openrouter 0.5`.
Add `--stop-after keyframes` (or `refs`, `clips`) to look at the results before the next paid stage.
`python -m adgen clean` deletes old runs.
