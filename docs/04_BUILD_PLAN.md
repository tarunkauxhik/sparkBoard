# 04 Build plan (final, 15 Nov 2026)

Where this conflicts with 01_PLAN_AND_DECISIONS.md, this file wins.
Goal: a simple, working pipeline plus 4 good samples, within approx $10 per key.

## 1. What the senior will judge, and how we cover it

| Judged on | How we cover it |
| --- | --- |
| Hyperrealism | Veo 3.1 for video, Nano Banana 2.1 keyframes, a realism layer in every prompt, text and logos added in code |
| Consistency | One identity portrait + outfit per character, a product pack, a location plate, the same refs in every call, face/product checks |
| Storyboard and script quality | Concepts from customer insights, a critic pass, natural spoken dialogue, a full shot spec per scene |
| How automated | One command runs brief to final ad; storyboard approval is optional (`--auto-approve`) |
| Variety | 4 formats, 3 languages, different looks per category |
| Code clarity | Small modules, Pydantic schemas, provider adapters, a README with one-command quickstart |

## 2. Keep it simple: what we cut

- No FastAPI server. A CLI (Typer) plus one small Streamlit app for the storyboard.
- No Reddit scraping. Research = brief + product page text (free fetch) + LLM knowledge. Web research is an optional flag.
- No SyncNet. Lip-sync is checked by word timing + the Gemini review.
- No upscaling service. ffmpeg lanczos scale 720p to 1080x1920 is enough for social.
- No self-hosting now. Mentioned as a future improvement.
- No Seedance, no Sarvam, no fal.

## 3. Stack (3 keys)

| Job | Model | Via | Approx price |
| --- | --- | --- | --- |
| Concepts, script, storyboard, edit list | Claude Sonnet 5.5 (`anthropic/claude-sonnet-5.5`) | OpenRouter | $2 / $10 per 1M tokens |
| QA review of images and clips | Gemini Flash (cheapest current Flash on OpenRouter) | OpenRouter | cents |
| Keyframes, portraits, packshots, statics | Nano Banana 2.1 (`nano-banana-2-1`, up to 10 ref images, 9:16) | Kie | approx $0.025 at 2K |
| Talking and hero video | Veo 3.1 Fast (`veo3_fast`) | Kie | approx $0.30 per clip (4, 6 or 8 s, 720p) |
| B-roll | Veo 3.1 Lite (`veo3_lite`) | Kie | approx $0.15 per clip |
| Lip-sync backup | Kling AI Avatar Standard (`kling/ai-avatar-standard`, image + audio, 720p) | Kie | per second |
| Voice swap, voiceover, transcripts, music | ElevenLabs Voice Changer, TTS v3, Scribe, Music | ElevenLabs | Voice Changer approx $0.12/min |
| Editing | ffmpeg | local | $0 |
| Local checks | insightface (face match), rapidocr (text), librosa + resemblyzer (voice) | local | $0 |

Kie facts: one endpoint `POST /api/v1/jobs/createTask`, poll Get Task Details. HTTP is 200 even on failure, so always check `code`. Images go in as URLs (upload with Kie's file upload API). Failed tasks are free.

## 4. The pipeline (one command)

`python -m adgen run briefs/skincare.json [--auto-approve] [--dry-run]`

| Step | Input | Output (in runs/<id>/) | Model |
| --- | --- | --- | --- |
| 1 Brief | brief JSON (brand, product, audience, goal, platform, language, optional refs and URL) | brief.json | none |
| 2 Insights | brief + product page text | insights.json (pains, desires, objections, proof points) | Sonnet |
| 3 Concepts | insights | concepts.json: 5 concepts, scored, winner + reason | Sonnet (write) then Sonnet (critic and score) |
| 4 Look | winner + category playbook | look.json: mood, tone, setting, camera, lens, light, palette, pacing, each with a reason | Sonnet |
| 5 References | look + user refs | refs/: character portraits, product pack, location plate | Nano Banana (only if not provided) |
| 6 Storyboard | concept + look + refs | storyboard.json (schema below) | Sonnet |
| 7 Approve | storyboard | approved flag (Streamlit editor, or auto) | none |
| 8 Keyframes | storyboard + refs | keyframes/ + checks | Nano Banana |
| 9 Clips | keyframes | clips/raw/ (every take kept) | Veo (Kling backup) |
| 10 Audio | clips + voice per character | clips/fixed/ (voice changed, checked) | ElevenLabs |
| 11 Edit | fixed clips + transcripts | edit_list.json | Sonnet, then code validation |
| 12 Render | edit list | final/ad_9x16.mp4 (+ 1x1), statics/ | ffmpeg, Pillow |
| 13 Final QA | final video | qa_report.json | Gemini + code checks |

Every step writes its file and is skipped on re-run if the file exists (resumable). `decision_log.jsonl` gets one line per decision (step, choice, reason, cost). A small script turns it into decision_log.md.

## 5. Key schemas (Pydantic)

Shot (one per scene):
```json
{
  "id": "s02",
  "purpose": "problem",
  "duration_s": 6,
  "shot_type": "medium close-up",
  "angle": "eye level, front phone camera",
  "framing": "head and shoulders, slightly off-center",
  "character": "riya",
  "speaker": "riya",
  "expression": "tired, half-smile",
  "action": "rubs her eyes, then looks into the lens",
  "lighting": "soft window light from the left, warm kitchen practicals",
  "location": "kitchen_plate",
  "product_visible": false,
  "dialogue_tts": "सुबह से थकान रहती है, honestly.",
  "dialogue_caption": "Subah se thakaan rehti hai, honestly.",
  "camera_move": "handheld, slight sway",
  "audio_notes": "room tone only, no music",
  "route": "veo_talk"
}
```
Routes: `veo_talk` (Veo speaks, then voice swap), `veo_broll` (no speech), `avatar_talk` (TTS + Kling Avatar), `vo_only` (Veo B-roll under TTS narration), `static`.

Edit list: same as diagram 3 (clips with in/out and a reason, B-roll over voice, audio leads, captions from word timings, music with ducking, end card).

## 6. Prompts (compiled by code, never hand-typed)

Storyboard JSON stays our data. Code turns each shot into a plain, labelled prompt in a fixed order:

`Camera: … Subject: … (identity from reference) Action: … Setting: … Lighting: … Dialogue: [speaker] says, in [language/accent]: "…" Audio: room tone only, no music. Avoid: subtitles, on-screen text, extra people, warped hands.`

Realism layer, added by category:
- UGC: "shot on a phone front camera, handheld, natural skin texture with pores, no makeup glow, slight noise"
- Hero/brand: a real lens and move ("85 mm, slow push-in"), one motivated light source, mixed color temperature, no golden-hour default

Rules: one speaker per clip; about 12–15 words per 6–8 s; speaking shots in medium close-up; product held simply or resting on a surface; same outfit and location words in every prompt for a character; `enable_translation: false` always (otherwise Hindi gets translated).

## 7. Category playbooks (tiny YAML files)

Skincare, fintech, gadgets, food and beverage, fashion: each sets light, lens, palette, set, pacing, music feel and caption style. The LLM adapts it to the brand and logs why.

## 8. Quality checks and retries

| Check | Where | Tool | Pass rule | On fail |
| --- | --- | --- | --- | --- |
| Face matches portrait | keyframes, clip frames (start, middle, end) | insightface cosine | ≥ 0.45 (tune in smoke test) | new seed, stronger ref |
| Product right | keyframes, product clips | Gemini rubric + OCR of brand word | brand word found, shape OK | re-anchor product image |
| No stray text | clip frames | OCR | no text unless planned | regenerate |
| Words right | fixed audio | Scribe vs script (key words) | all key words present, last word not cut | regenerate clip (Veo route) or TTS line (avatar route) |
| Voice consistent | all lines of a character | resemblyzer | ≥ 0.80 to that character's first line | voice changer again, pitch-matched input |
| Artifacts and brief | keyframes, clips (480p copy) | Gemini rubric | no major issue | prompt patch from critique, regenerate |
| Final cut | final video | Gemini + ffprobe, blackdetect, silencedetect, loudness | -14 LUFS ±1, A/V length match, no black/silent gaps | fix edit list, re-render (free) |

Retry policy: keyframes max 3 tries (cheap). Clips max 2 tries, then switch route (Veo → Kling Avatar), then flag in the QA report. Budget guard stops everything at the per-ad cap.

## 9. The small mistakes that ruin AI ads (and our guard)

| Mistake | Guard |
| --- | --- |
| Veo translates Hindi dialogue to English | `enable_translation: false` |
| Burned-in subtitles or random text | prompt "no subtitles", OCR reject |
| Veo adds music | prompt "no music", voice isolation, our own music bed |
| Line too long, last word cut (seen in the senior's clip 2) | max words per second check in storyboard; Scribe must hear the last word |
| Voice changes between clips | voice changer to one voice per character, pitch-matched |
| Loudness jumps between clips | loudnorm per clip and on the master |
| Clothes, hair or room change between shots | identity portrait with outfit, location plate, same words in every prompt |
| Product changes size, label or hand | product pack as ref, simple holds, OCR + Gemini check |
| Hands merging with the product | simple actions only, Gemini hand check |
| Keyframe and video start don't match | first-frame mode from the same keyframe; face check at t=0 |
| Frozen or warped last frames | trim to the spoken words plus 0.15 s |
| Cutting mid-word | cuts snap to word gaps from Scribe timings |
| Mixed fps (Veo 24, Kling 48) | everything normalized to 1080x1920, 24 fps, yuv420p, 48 kHz before joining |
| Audio drift after joining | one master audio track, mux once, no `-shortest` |
| Captions hide the face or product, or sit under app buttons | captions in the safe zone (about 62–72% of height), max 2 lines, max 4 words per chunk |
| Hinglish captions break (Devanagari shaping) | captions use the Roman `dialogue_caption`; TTS uses mixed script (Hindi in Devanagari, English in Latin) |
| Brand name misspelled or mispronounced | brand name stored once in the brief; captions and logo from code; pronunciation check by Scribe |
| Weak first 2 seconds | the storyboard's first shot must be the hook; Gemini checks the first frame |
| No CTA or unreadable end card | end card from code: logo, one line, 1.5–2 s |
| Unprovable claims (health, money) | critic pass flags claims; brands are fictional; "AI-generated" note in README |
| "AI look" (glossy, golden, centered) | realism layer, mixed light, off-center framing, light grain at render |
| Hidden costs (duplicate jobs, retries) | task ID saved before polling, never resubmit on timeout, ledger with hard cap |

## 10. Samples (keep them short)

| # | Brand (fictional) | Format | Language | Length | Routes |
| --- | --- | --- | --- | --- | --- |
| 1 | Skincare serum | UGC testimonial | Indian English | 15–20 s | 3 veo_talk + 1 veo_broll |
| 2 | Bill-split fintech app | 2-person role-play | Hinglish | 20–25 s | 4 veo_talk (shot/reverse-shot) + 1 broll |
| 3 | Wireless earbuds | Product hero video + 3 statics | US English VO | 10–15 s | 2 veo_broll + vo_only + static |
| 4 | Coffee brand | Brand story | English narration | 20 s | 3 veo_broll (Lite) under TTS narration |

Exports: 9:16 video for each; statics in 1:1, 4:5 and 9:16 for sample 3.

## 11. Budget per key (approx, with retries)

| Key | Smoke test | Samples | Dev and buffer | Total |
| --- | --- | --- | --- | --- |
| Kie ($10) | $1.0 | UGC $1.8, role-play $2.2, product $0.8, brand $0.9 | refs $0.3 | approx $7 |
| ElevenLabs (approx $9.50 left) | $0.1 | voice swap approx 2 min, VO, Scribe, music | | approx $1–1.5 |
| OpenRouter ($10) | $0.1 | approx $0.4 per sample | dev prompts approx $1 | approx $3 |

Hard caps in code: $3 Kie per sample, $0.50 ElevenLabs per sample, $1 OpenRouter per sample. Every paid run asks for Tarun's OK first.

## 12. Build phases (each ends with a commit)

| Phase | What | Paid? | Done when |
| --- | --- | --- | --- |
| 0 Setup | repo, CLAUDE.md, docs/, .env, requirements, fonts | no | `pytest` runs |
| 1 Skeleton | schemas, run folder, ledger, decision log, CLI, mock providers | no | full dry run creates every JSON file |
| 2 Editor | ffmpeg normalize, trim, edit list validator, captions, master audio, end card, statics layout | no | dry run renders a real mp4 from test clips |
| 3 Brain | insights, concepts + critic, look, storyboard prompts (OpenRouter) | cents | 4 briefs give 4 good storyboards; review them together |
| 4 Smoke test | Kie: one keyframe, one Veo talk (English), one Veo talk (Hinglish), one Kling Avatar; ElevenLabs voice swap | approx $1–1.5 | face filter answer, routes confirmed, thresholds tuned |
| 5 Generate | keyframes, clips, audio fix, QA loop, retries, budget guard | yes | sample 1 end to end |
| 6 Samples | samples 2–4 | yes | all 4 pass final QA |
| 7 Streamlit + docs | storyboard editor, README, ARCHITECTURE.md, LIMITATIONS.md | no | a stranger can run it from README |

## 13. What we send to the senior

- GitHub repo link (README: what it does, one-command quickstart, diagram, sample table)
- Drive folder: 4 sample videos + statics, and per sample: storyboard.json, decision_log.md, qa_report.json
- ARCHITECTURE.md (modules, tools, models, what changed from the approach and why)
- LIMITATIONS.md (short: limits and what we'd improve)
- A short humanized email with both links
