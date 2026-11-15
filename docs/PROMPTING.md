# Prompting and API rules

Every rule the code follows when it writes prompts and API requests, with its source.
Sources were read on 16 Nov 2026. **Re-check all of them before phase 4** (the smoke test):
model APIs change often.

"Official" means the rule comes from the vendor's own page. "Practitioner" means it is our
own rule or common advice, not confirmed by the vendor.

## Sources

| Short name | Page | Published |
| --- | --- | --- |
| Veo guide | https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-veo-3-1 | 16 Oct 2025 |
| Nano Banana guide | https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-nano-banana | 6 Mar 2026 |
| Kie Veo | https://docs.kie.ai/veo3-api/generate-veo-3-video.md | read 16 Nov 2026 |
| Kie Nano Banana | https://docs.kie.ai/market/google/nanobanana-2-1.md | read 16 Nov 2026 |
| Kie Kling Avatar | https://docs.kie.ai/market/kling/ai-avatar-standard.md | read 16 Nov 2026 |
| Kie task details | https://docs.kie.ai/market/common/get-task-detail.md | read 16 Nov 2026 |
| Kie file upload | https://docs.kie.ai/file-upload-api/upload-file-stream.md | read 16 Nov 2026 |
| ElevenLabs v3 | https://elevenlabs.io/docs/best-practices/prompting/eleven-v3 | read 16 Nov 2026 |

## Kie API requests (code: `adgen/providers/kie.py`)

| Rule | Source | Kind |
| --- | --- | --- |
| One endpoint for all models: `POST https://api.kie.ai/api/v1/jobs/createTask`, body `{model, input, callBackUrl?}` | Kie Veo, Kie Nano Banana, Kie Kling Avatar | Official |
| HTTP is 200 even on failure: always check `code` in the body | Kie Veo | Official |
| Veo: top-level `model` is `veo-3-1`; the tier goes in `input.model`: `veo3_fast`, `veo3_lite` or `veo3` | Kie Veo | Official |
| Veo `input` fields are snake_case: `prompt`, `image_urls`, `generation_type`, `aspect_ratio`, `resolution`, `duration`, `enable_translation`, `watermark` | Kie Veo | Official |
| Veo `duration` exists: an integer, 4, 6 or 8 (default 8) | Kie Veo | Official |
| Veo `generation_type`: `TEXT_2_VIDEO`, `FIRST_AND_LAST_FRAMES_2_VIDEO` (1 or 2 images), `REFERENCE_2_VIDEO` (1 to 3 images, 8 s only, fast and lite tiers only) | Kie Veo | Official |
| Veo `aspect_ratio`: `16:9` (default), `9:16`, `Auto`. `resolution`: `720p` (default), `1080p`, `4k` | Kie Veo | Official |
| Veo has **no seed field**. A re-roll is a new task | Kie Veo (field not documented) | Official |
| Always send `enable_translation: false`; when true the prompt is translated to English, which breaks Hindi dialogue. The page gives no default, so we never rely on one | Kie Veo | Official (field), practitioner (our rule) |
| `enable_fallback` is deprecated: never send it | Kie Veo | Official |
| We do not send `watermark` (we want none) or `callBackUrl` (we poll and have no public URL) | our choice | Practitioner |
| Nano Banana: `model` is `nano-banana-2-1`; `input` has `prompt` (max 20,000 characters), `image_input` (max 10 URLs, jpeg/png/webp, 30 MB each), `aspect_ratio` (includes `9:16`, `4:5`, `1:1`), `resolution` (`1K`, `2K`, `4K`), `output_format` (`png`, `jpg`) | Kie Nano Banana | Official |
| Nano Banana has **no seed field** | Kie Nano Banana (field not documented) | Official |
| Kling Avatar: `model` is `kling/ai-avatar-standard`; `input` has `image_url` (jpeg/png, 10 MB), `audio_url` (max 100 MB, 5 minutes) and a required non-empty `prompt` (max 5,000 characters). Output is 720p and as long as the audio | Kie Kling Avatar | Official |
| Poll `GET /api/v1/jobs/recordInfo?taskId=...`. States: `waiting`, `queuing`, `generating`, `success`, `fail`. `resultJson` is a JSON string holding `resultUrls`. On `fail` read `failCode` and `failMsg` | Kie task details | Official |
| Start polling every 2 to 3 seconds and slow down. Video can take over 10 minutes. Save the task ID first and never resubmit on a timeout | Kie task details (polling), our rule (no resubmit) | Official + practitioner |
| Generated files are kept 14 days; uploaded input files are deleted after 24 hours. Download results at once; re-upload references if a run is resumed a day later | Kie task details, Kie file upload | Official |
| Images and audio go in as URLs. Upload with `POST /api/file-stream-upload` (form fields `file`, `uploadPath`, `fileName`); use `data.downloadUrl` from the reply | Kie file upload | Official |
| Failed tasks report `creditsConsumed: 0` | Kie Nano Banana, Kie Kling Avatar (callback examples) | Official |

Open points to confirm in the smoke test: the upload host (the page shows both `api.kie.ai`
and `kieai.redpandaai.co`), real credit prices per model, and Kling Avatar's frame rate
(not stated in the docs).

## Veo video prompts (code: `motion_prompt` in `adgen/prompts.py`)

| Rule | Source | Kind |
| --- | --- | --- |
| Plain prose in this order: Cinematography, Subject, Action, Context, Style and ambience | Veo guide | Official |
| Timed beats inside one clip are written as `[00:00-00:02] ...` | Veo guide | Official |
| Dialogue goes in quotation marks after the speaker | Veo guide (`A woman says, "..."`) | Official |
| We write dialogue as `<name> says, in <language>, <accent>: "<line>"` so the accent is fixed per persona | our format, built on the official one | Practitioner |
| Room sound is written as `Ambient noise: ...`; effects as `SFX: ...` | Veo guide | Official |
| Say what you want instead of listing what you don't ("a clean frame without captions", not a "no ..." list) | Veo guide | Official |
| Reuse the same reference images and the same persona words in every shot of a scene | Veo guide | Official |
| The subject line ends with "the same person as in the reference image" | our rule | Practitioner |
| One speaker per clip; the speaker is turned toward the camera; speaking shots use a static or light handheld camera | our rule (lip-sync and voice swap work best this way) | Practitioner |
| Each shot has 1 or 2 beats, each one physical action plus an eye-line; no emotion-only directions | our rule | Practitioner |
| Clips are 4, 6 or 8 s, 720p or 1080p, 16:9 or 9:16 | Veo guide, Kie Veo | Official |

## Nano Banana image prompts (code: `keyframe_request`, `character_sheet_prompt` in `adgen/prompts.py`)

| Rule | Source | Kind |
| --- | --- | --- |
| Write a narrative description, not a keyword list; start with a strong verb | Nano Banana guide | Official |
| With references: reference images + what each one is for + the new scene | Nano Banana guide | Official |
| Name each reference's role ("image 1: face and hair of Meera; image 2: product bottle, keep the label exactly") | Nano Banana guide (role example), our numbering | Official + practitioner |
| Name the camera, lens and f-stop, and one light source | Nano Banana guide | Official |
| UGC look: "smartphone front camera, handheld, natural window light, visible pores and skin texture, slight noise, unretouched" | our wording | Practitioner |
| Never write "8K", "cinematic", "flawless" or similar: they push the image toward a glossy AI look. (Google's guide does use "cinematic color grading"; we still avoid the word) | our rule | Practitioner |
| Describe what you want, not what you don't ("empty street", not "no cars") | Nano Banana guide | Official |
| Edits say what changes and what stays exactly the same | Nano Banana guide | Official |
| Build one multi-angle character sheet per persona and pass it as image 1 in every shot with that persona | our rule; the guide only says references help character consistency | Practitioner |
| Keyframes contain no text. Captions, logos and end cards are added in code | our rule | Practitioner |
| The clean packshot is passed in every shot where the product is visible. If OCR cannot read the brand word on the result, the real label is composited in code (phase 5) | our rule | Practitioner |
| The model accepts up to 14 reference images; Kie's API accepts at most 10 | Nano Banana guide, Kie Nano Banana | Official |

## ElevenLabs voice (used from phase 4)

| Rule | Source | Kind |
| --- | --- | --- |
| v3 audio tags go in square brackets before or after the words: `[sighs]`, `[laughs]`, `[whispers]` | ElevenLabs v3 | Official |
| Ellipses add a pause; capitals add emphasis; SSML `<break>` is not supported in v3 | ElevenLabs v3 | Official |
| Tags that clash with the voice, or that the voice was not trained on, are unreliable | ElevenLabs v3 | Official |
| At most one tag per line, and only on lines voiced by TTS. Tags are removed from lines that Veo speaks | our rule | Practitioner |
| Eleven v4 (`eleven_v4`) is recommended over v3 for Voice Library voices and professional clones. The smoke test compares v3 and v4 on a library voice and a cloned voice | ElevenLabs v3 | Official (v4 advice), practitioner (the A/B) |
| Hinglish: the TTS text is mixed script (Hindi in Devanagari, English in Latin); captions are Roman only | our rule, from the voice-fix task | Practitioner |
| Voice Changer settings that worked: `eleven_multilingual_sts_v2`, stability 0.5, similarity 0.85, pitch-matched input | our voice-fix task (15 Nov 2026) | Practitioner |

## Script and storyboard rules (code: `adgen/rules.py`, `adgen/schemas.py`, `adgen/brain.py`)

All of these are our own rules (practitioner). "Code" means the pipeline rejects a storyboard
that breaks it; "prompt" means the writer and critic are told, but code cannot check it.

| Rule | Checked by |
| --- | --- |
| Spoken lines: about 2.2 words per second with 0.5 s of silence at each end, counted on the Roman caption. Code sets each spoken shot to the shortest of 4, 6 or 8 s that fits | Code |
| Total length within 2 s of the brief's target | Code |
| The first shot is the hook; its line is 8 words or fewer and does not start with a warm-up word (okay, so, hey, well ...) | Code |
| The hook type is one of: first-use reaction, drop-in mid-scene, symptom diagnosis, contrarian, third-person proof, and is logged with its reason | Code |
| The hook makes no product claim (no feature list in the hook) | Code, from the critic's claim check |
| Banned: ring-light set-ups, exclamation marks (forced enthusiasm), "game changer", "I was skeptical", "hey guys" and similar stock phrases | Code |
| UGC and product ads show the product in shot 1; a UGC ad has at least one silent b-roll shot; a product ad has at least one static shot | Code |
| The last spoken shot is the soft call to action | Code (its purpose is "cta"); the wording is checked by the critic |
| Every claim in every spoken line is listed with the product fact that backs it | Code |
| Cast: fictional adults of 25 or older, never a likeness; each persona has look, outfit, 2 to 3 speech habits, pace, energy and accent | Code |
| On-camera speaking shots are medium close-ups with a static or light handheld camera | Code |
| Each shot has 1 or 2 timed beats inside its length, each with an action and (if a person is on screen) an eye-line | Code |
| Code counts the words itself and sets every spoken shot's length; the model's own count and its `plan` are replaced by the real numbers, which are also sent back with every rejection | Code |
| Each spoken shot has its own `delivery` (how that line is said), its own `setting` (only what is visible in that shot) and exactly one `lens` | Code (present, one lens); the wording is the writer's |
| UGC selfie speaking shots use a light handheld camera | Code |
| Hands-only shots (`face_visible` false) do not get the character sheet | Code |
| Brand story and product hero ads are told in voiceover over b-roll, with at most one on-camera line; their cast includes an off-screen narrator | Code |
| Static headlines and the end card line get the same claim check as spoken lines | Code |
| Printed text other than the brand name (a date, a price) is added in code later; the keyframe leaves that label area blank | Code (prompt compiler), writer marks it in `blank_label_text` |
| A new on-screen persona must differ from personas used for other brands: another name, at least 4 years apart in age, and at most 30% of the same look words | Code (`adgen/casting.py`) |
| Critic notes are at most two plain sentences per field; any word count they state must equal the real one | Code |
| Natural speech: contractions, short sentences, at most one filler or self-correction per ad | Prompt, critic |
| No emotion-only directions; shots that depend on micro-expressions are flagged | Prompt, critic |
| No action carried across a cut: each shot opens on a settled pose | Prompt, critic |

## Quality checks (phase 5; thresholds are tuned on our own smoke test data)

| Check | Rule | Status |
| --- | --- | --- |
| Words | Scribe transcript against the script: word error rate above 10% fails | Function built (`adgen/qa.py`) |
| Clip rubric | Gemini scores 1 to 5 for hands, label, lip sync, "AI look" and hook strength; any score below 3 is re-rolled | Rule built (`adgen/qa.py`); the Gemini call is phase 5 |
| Stray text | OCR on the first, middle and last frame of every clip; any unplanned text fails | Phase 5 (needs an OCR library; size to be approved first) |
| Face | Similarity to the character sheet; threshold tuned in the smoke test | Phase 5 |
