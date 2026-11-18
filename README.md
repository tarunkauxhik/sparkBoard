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

## Samples

Four ads made end to end by the pipeline, each from a reviewed storyboard. Every folder in
`samples/` also holds the brief, insights, concepts, look, every take's check results, the edit
list and the cost ledger.

| # | Brand (fictional) | Format | Language | Length | Video | Storyboard | Decision log | QA report |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Dewline serum | UGC | Indian English | 15.5 s | [ad_9x16.mp4](samples/skincare/ad_9x16.mp4) | [storyboard.md](samples/skincare/storyboard.md) | [decision_log.md](samples/skincare/decision_log.md) | [qa_report.json](samples/skincare/qa_report.json) |
| 2 | Chukta bill-split app | Role-play | Hinglish | 17.9 s | [ad_9x16.mp4](samples/fintech/ad_9x16.mp4) | [storyboard.md](samples/fintech/storyboard.md) | [decision_log.md](samples/fintech/decision_log.md) | [qa_report.json](samples/fintech/qa_report.json) |
| 3 | Noctave earbuds | Product hero + statics | US English | 9.3 s | [ad_9x16.mp4](samples/earbuds/ad_9x16.mp4) | [storyboard.md](samples/earbuds/storyboard.md) | [decision_log.md](samples/earbuds/decision_log.md) | [qa_report.json](samples/earbuds/qa_report.json) |
| 4 | Brasswick coffee | Brand story | English | 14.1 s | [ad_9x16.mp4](samples/coffee/ad_9x16.mp4) | [storyboard.md](samples/coffee/storyboard.md) | [decision_log.md](samples/coffee/decision_log.md) | [qa_report.json](samples/coffee/qa_report.json) |

Static ads for sample 3: [1:1](samples/earbuds/s04_1x1.png), [4:5](samples/earbuds/s04_4x5.png),
[9:16](samples/earbuds/s04_9x16.png).

Each QA report is honest about what is still wrong: one speaker's voice changing pitch between
clips, a face that drifts as the person turns away, a few taps left in the background sound.
See [docs/LIMITATIONS.md](docs/LIMITATIONS.md). How it works: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
