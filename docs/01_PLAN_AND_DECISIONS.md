# Plan and decisions (agreed, Nov 2026)

These decisions came out of research and testing. Change them only with a clear reason, and log the change.

## Stack (3 keys only)

| Job | Tool | Via | Approx cost |
| --- | --- | --- | --- |
| Research, ideas, script, storyboard, edit list | Claude Sonnet 5.5 | OpenRouter | cents per ad |
| Clip and final-cut review (QA) | Gemini Flash | OpenRouter | cents per ad |
| Keyframes and static ads | Nano Banana 2.1 | Kie AI | approx $0.02–0.04 per image |
| Video (default) | Veo 3.1 Fast | Kie AI | approx $0.30 per clip up to 8 s (720p) |
| Video drafts, simple B-roll | Veo 3.1 Lite | Kie AI | approx $0.15 per clip |
| Lip-sync from audio (route B) | Kling AI Avatar | Kie AI | approx $0.05 per second |
| Music | Suno | Kie AI | small |
| Voices, voice swap, isolation | ElevenLabs TTS, Voice Changer, Voice Isolator | ElevenLabs | Voice Changer approx $0.12/min |
| Transcripts with word timings | ElevenLabs Scribe (paid), faster-whisper (free, local) | | Scribe approx $0.20/hour |
| Editing and assembly | ffmpeg (free) | local | $0 |
| Free local QA | resemblyzer (voice match), librosa (pitch), ArcFace (face), OCR, SyncNet | local | $0 |

Kie notes: credits approx $0.005 each, failed tasks are not charged, credits don't expire. Images go in as URLs. Veo audio on Kie is marked "experimental".

Dropped on purpose: Sora (API shut down Sep 2026), Veo via fal (being removed on Nov 17 2026), Seedance (rejects real faces, costly).

Changes from the approach email (explain these in the final architecture doc, don't email them now): Veo 3.1 via Kie added at the senior's suggestion; Seedance dropped (rejects real faces, costly); Sarvam dropped (ElevenLabs covers Hindi voice, keeps us to 3 keys).

## Pipeline (7 steps)

1. Research: product page, reviews, Reddit, competitor ads, turned into an insight bank of real customer words.
2. Ideate: 6–8 concepts, each tied to an insight. A critic pass kills generic ones. Score on hook, brief fit, platform fit, AI feasibility, distinctiveness and cost. The winner is picked with a written reason.
3. References: character sheet per person, product pack, location plate, brand kit. User-provided or generated.
4. Storyboard and script as JSON: per scene, the shot, angle, framing, expression, action, lighting, dialogue and duration. Editable, with optional approval.
5. Audio: one fixed voice per character, every line checked against the script.
6. Visuals: keyframe first, then video. Talking shots use route A or B (below).
7. Assemble with ffmpeg, then a final check.

Every step saves JSON in a run folder, so runs can be resumed and single shots redone.

## Talking shots: two routes

- Route A (English, default): keyframe, then Veo says the line. Voice Isolator, then Voice Changer to the character's fixed voice (timing is unchanged, so lip-sync holds). Then the transcript must match the script and sync is measured.
- Route B (Hinglish, long lines, or when A fails twice): ElevenLabs voices the line, the transcript is checked, then Kling Avatar makes the keyframe speak that audio.
- Rules: one speaker per clip (two people in one Veo clip would get the same swapped voice). Reaction shots are prompted as silent. 4–8 s per clip, about 15 words max. Medium close-up for speaking shots. Prompt "no music, no subtitles", plus an OCR check for burned-in text.

## Editing (how everything becomes one video)

1. Collect approved clips, voice lines, B-roll, music, brand files.
2. Trim each clip to its words using transcript word timings, with small padding.
3. Claude writes the edit list (JSON timeline): shot order, in/out points, B-roll over dialogue, audio leads (J/L cuts), captions, music, logo, end card. Each choice has a "why".
4. Code validates it: files exist, no gaps, length fits the platform.
5. Render the picture: normalize every clip to the same size, fps, pixel format and audio format first (avoids audio drift), then join.
6. Build sound as one master track: voice, room tone, SFX, music ducked under voice, -14 LUFS, true peak -1.5.
7. Finish: captions from word timings (ASS), logo and text from real brand files, exports 9:16, 1:1, 16:9.
8. Final check: Gemini watches the cut, code checks A/V length, black frames, silence, loudness. On a fail, fix the edit list and re-render. No new clips needed.

## Prompting

- Keep JSON for our own data (storyboard, shot spec, edit list). Code compiles each shot spec into a labelled plain-language prompt in a fixed order: camera, subject, action, setting, dialogue, audio, negatives. A test found JSON prompts give no better images than good plain prompts. A/B test on Veo later.
- Realism layer: real skin texture, one named light source, phone-camera look for UGC, simple hand actions, product photo attached to every call, text and logos composited in code (never generated).

## Known risks and how we handle them

| Risk | Handling |
| --- | --- |
| Veo blocks AI-made faces in image-to-video (reported on Google's API, false "celebrity/child" flags) | Day-1 smoke test on Kie. Fallback: reference-to-video, then Kling route B. Failed Kie tasks are free |
| Veo audio dropped by safety filter | ASR check catches missing speech, then retry or route B |
| Veo/Kling weak at Hindi | Hinglish goes through route B; test one Hindi line first |
| Veo adds music or subtitles | Prompt negatives, Voice Isolator, OCR reject |
| Voice drift between clips | Voice Changer to one fixed voice, pitch-matched (see voice fix report) |
| Audio drift when joining | Normalize every clip before concat; one master audio track |
| Hidden cost from duplicate jobs | Save task ID before polling; never resubmit on a poll timeout |

## Testing plan (protects the budget)

1. Smoke test (approx $1–2 on Kie): one AI face through Veo (image-to-video and reference mode), one English line on route A, one Hindi line on route B.
2. Dry-run mode ($0): the full pipeline with placeholder clips, to find code and editing bugs for free.
3. One full sample at 720p, fix what breaks, then the other three.
4. Guards in code: per-ad dollar cap, max 3 tries per shot, ledger of every paid call, drafts at 720p, QA every still before animating it, low-res copies for Gemini review.

Estimated Kie spend: smoke test $1.5, UGC $3, role-play $1.5, product ad $1, brand ad $1.5, total about $8.5 of $10.

## Samples planned

| Sample | Format | Language |
| --- | --- | --- |
| Skincare serum | UGC testimonial, ~20 s | Indian English |
| Fintech app | 2-person role-play, ~25 s | Hinglish |
| Earbuds | Product hero video + statics | US English VO |
| Coffee brand | Brand story, ~30 s | US English narration |

Brands are fictional unless the senior provides real ones.

## Self-hosting (later, not now)

LTX-2.5, FLUX.2, InfiniteTalk and the QA models can run on a rented GPU (RunPod RTX 4090 approx $0.35–0.90/hr), giving draft video under 1 cent per second. Keep paid models for final close-up faces.
