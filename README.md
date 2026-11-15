# sparkBoard

Turns a brand brief into checked ad creatives (images and videos) with one command.
Work in progress: see [docs/04_BUILD_PLAN.md](docs/04_BUILD_PLAN.md).

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
`python -m adgen clean` deletes old runs.
