# Architecture

sparkBoard turns a brand brief into a checked ad: a storyboard, a 9:16 video and, for product
ads, static ads. One command runs the whole way; every step saves its output, so a run can stop
and continue, and nothing that cost money is ever paid for twice.

```
python -m adgen run briefs/skincare.json --dry-run --auto-approve          # free, mock providers
python -m adgen run briefs/skincare.json --live --auto-approve \
    --cap-kie 2 --cap-elevenlabs 0.3 --cap-openrouter 0.5 --isolate-voice  # paid, capped per service
```

The rules behind every prompt and API field, with their sources, are in [PROMPTING.md](PROMPTING.md).
What it cannot do yet is in [LIMITATIONS.md](LIMITATIONS.md).

## The flow

| # | Step | Output (in `runs/<run_id>/`) | Made by | Checked by code |
| --- | --- | --- | --- | --- |
| 1 | Brief | `brief.json` | the user | schema: brand, format, product facts, target length |
| 2 | Insights | `insights.json` | Claude Sonnet | proof points may only restate product facts |
| 3 | Concepts | `concepts.json` | Sonnet writes 5; a separate Sonnet critic scores 5 criteria | code picks the highest total |
| 4 | Look and cast | `look.json` | Sonnet, from the category playbook | no glossy "AI look" words, no brand names, a narrator for voiceover formats, cast must differ from other brands |
| 6 | Storyboard | `storyboard.json`, `storyboard.md` | Sonnet draft, then a Sonnet script editor | the script and shot rules (below) |
| 7 | Approval | `approval.json` | the user, or `--auto-approve` | |
| 5 | References | `refs/` | Nano Banana: a character sheet per person, packshot, location plate; app screens are drawn in code | sheets of different people must score under 0.45 on the face check |
| 8 | Keyframes | `keyframes/` | Nano Banana, with the references; label text (a date) written in by code, where Gemini finds the blank label | face against the sheet; up to 3 tries |
| 9 | Clips | `clips/raw/` | Veo 3.1 Lite, starting from the keyframe | words (Scribe transcript) and face against the keyframe; up to 2 takes, then flagged |
| 10 | Audio | `clips/fixed/` | ElevenLabs voice isolator (optional) | stray clicks between words are found and muted |
| 11 | Edit list | `edit_list.json` | code | each spoken clip trimmed to its words plus `--trim-pad` |
| 12 | Render | `final/ad_9x16.mp4`, `statics/` | ffmpeg and Pillow | edit list validated first |
| 13 | Final QA | `qa_report.json` | code, plus a Gemini review as hints | lengths, loudness, black or silent gaps, clicks, voice pitch, every flagged shot |

References (5) are made after the storyboard (6) because only the people who appear on screen
need a character sheet. Every step also adds a line to `decision_log.jsonl`: the step, what was
chosen, why, and what it cost. `decision_log.md` is the readable copy.

A live run can stop after `refs`, `keyframes` or `clips` (`--stop-after`) so a person can look
before the next paid stage; the same `--run-id` continues.

## Modules

| Module | Job |
| --- | --- |
| `adgen/__main__.py` | The command line: `run`, `smoke`, `clean`, `save-sample`, `fetch-face-model` |
| `adgen/pipeline.py` | The 13 steps and the retry loops |
| `adgen/schemas.py` | Pydantic models for every JSON file, with the single-shot rules (word counts, durations, beats, script) |
| `adgen/rules.py` | Rules that need the brief or the cast: hook, length, cast use, claims, routes, banned words |
| `adgen/brain.py` | What each LLM task is asked and the JSON it must return |
| `adgen/prompts.py` | Compiles storyboard data into Nano Banana and Veo prompts. Prompts are never hand-typed |
| `adgen/casting.py` | Keeps personas of different brands apart |
| `adgen/faces.py` | Local face check: SCRFD finds the face, ArcFace compares two faces (insightface `buffalo_sc`, 15 MB) |
| `adgen/clicks.py` | Finds and mutes stray clicks and taps between words |
| `adgen/voice.py` | Measures a voice's pitch, to warn when one speaker sounds different between clips |
| `adgen/qa.py` | The pass and fail limits (word errors, face scores, retries, pitch) |
| `adgen/editor.py` | ffmpeg: trims, normalizing, one master audio track, captions, end card, final checks |
| `adgen/statics.py` | Pillow: end card, static ads, app screens. All brand text is drawn in code |
| `adgen/ledger.py` | Every paid call is checked against a hard cap before it is sent, and recorded after |
| `adgen/report.py` | `storyboard.md` and `decision_log.md` |
| `adgen/providers/` | The only place that talks to a model: `openrouter.py`, `kie.py`, `elevenlabs.py`, the `live.py` provider that joins them, and `mock.py` for free dry runs |
| `adgen/smoke.py` | The smoke test that measured prices, formats and failure modes before any full run |

## Models and services

| Job | Model | Service | Measured price |
| --- | --- | --- | --- |
| Insights, concepts, look, storyboard, critics | Claude Sonnet 5.5 | OpenRouter | about $0.12 per storyboard |
| Character sheets, packshots, keyframes | Nano Banana 2.1 at 2K | Kie | $0.03 per image |
| Video clips | Veo 3.1 Lite, 720p | Kie | $0.15 per clip (a flat price for 4 and 6 s) |
| Transcripts with word timings | Scribe v3 | ElevenLabs | under a cent per clip |
| Removing room echo | Voice Isolator | ElevenLabs | about a cent per clip |
| Voiceover lines | Eleven v4 | ElevenLabs | about 160 credits for one short line |
| Final review (hints only), finding a blank label area | Gemini 3.1 Flash Lite | OpenRouter | under a cent |
| Face check | insightface `buffalo_sc` (local) | none | free |
| Editing | ffmpeg, Pillow (local) | none | free |

Only three API keys are used (Kie, OpenRouter, ElevenLabs), each with a budget of about $10.

## How the main problems are handled

**Cost.** Every paid call goes through the ledger. Before a call, the worst case is checked
against the cap: input size plus the full output limit for LLMs, an assumed high price for Kie
tasks. After the call, the real cost is recorded (OpenRouter's usage data; Kie's credit balance
before and after). A Kie task ID is saved before polling, so a slow task is waited for again,
never submitted twice. Dry runs are the default.

**Consistency of faces.** One character sheet per person (four views) is passed as image 1 to
every keyframe, and the person's description is repeated word for word in every prompt. A local
face model then checks each keyframe against the sheet and each clip against its keyframe. A
face only passes if it is close enough to its own person *and* closer to them than to anyone
else in the cast: two personas that looked alike scored 0.66 against each other, so a fixed
limit alone was not enough.

**Consistency of the product.** The clean packshot is passed in every shot that shows the
product, with its label text spelled out. App screens are drawn in code and passed as the
reference. Dates or prices on a label are left blank by the image model and written in by code.

**Script quality.** Code counts the words and sets each shot's length (about 2.2 words per
second, with half a second of quiet at each end). The hook opens on the tension, every claim
must cite a product fact, the last line is a soft call to action, and a second LLM pass rewrites
anything that sounds like ad copy. Most of these rules are checked in code; a storyboard that
breaks one is sent back once with the errors, then rejected.

**Sound.** Speaking shots ask Veo for a close, dry voice. The voice isolator removes room echo,
a faint room-tone bed is added back, and clicks between words are muted. Every clip is brought
to the same size, frame rate and sample rate before joining, one master track is built, and the
result is levelled to -14 LUFS.

**Self-repair.** A keyframe with the wrong face is re-made (up to 3 tries). A clip with wrong or
cut-off words, or a drifting face, gets one more take; after that it is flagged in the QA report
rather than retried forever.

## What changed from the original approach, and why

| Approach email | Now | Why |
| --- | --- | --- |
| Kling 3.0 and Seedance 2.5 for video | Veo 3.1 through Kie | The senior suggested Veo (the same model as Google Flow). Seedance rejects real-looking faces and costs more |
| Veo Fast as the default | Veo Lite | Half the price ($0.15 against $0.30 per clip) and comparable frames in a side-by-side test |
| Sarvam for Hindi voice | ElevenLabs only | ElevenLabs handles Hindi and Hinglish, and it keeps the project to three keys |
| ElevenLabs Voice Changer to give every clip one fixed voice | Dropped | In testing it added a loud click and turned the name "Rohan" into "Roman" |
| Voice match by voice changer | Voice isolator plus a pitch warning | The isolator removes Veo's room echo without changing the voice; voice differences between clips are flagged, not fixed |
| InfiniteTalk or Kling Avatar for lip-sync | Kling Avatar kept only as a documented fallback | In testing its speaker turned away from the camera and the lip-sync was off |
| Gemini for face, product and artifact checks | A local face model; Gemini only gives hints | Two Gemini models both called two different people "the same person" |
| Claude writes the edit list | Code builds it from the word timings | Trims follow exact word timings, and it saves one paid call |
| Reddit and competitor ads as research | The brief, its product facts and the model's knowledge | Kept simple; every claim must trace back to a product fact |
| FastAPI server | A command line (a small Streamlit storyboard editor is planned) | Simpler to run and to review |
| SyncNet lip-sync score | Word timing checks and the transcript | Avoids a large model download |
