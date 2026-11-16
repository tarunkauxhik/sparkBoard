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
| Kling Avatar is a documented fallback only; no sample uses it (in the smoke test its speaker turned away and the lip-sync was off) | our choice | Practitioner |
| Kling Avatar: `model` is `kling/ai-avatar-standard`; `input` has `image_url` (jpeg/png, 10 MB), `audio_url` (max 100 MB, 5 minutes) and a required non-empty `prompt` (max 5,000 characters). Output is 720p and as long as the audio | Kie Kling Avatar | Official |
| Poll `GET /api/v1/jobs/recordInfo?taskId=...`. States: `waiting`, `queuing`, `generating`, `success`, `fail`. `resultJson` is a JSON string holding `resultUrls`. On `fail` read `failCode` and `failMsg` | Kie task details | Official |
| Start polling every 2 to 3 seconds and slow down. Video can take over 10 minutes. Save the task ID first and never resubmit on a timeout | Kie task details (polling), our rule (no resubmit) | Official + practitioner |
| Generated files are kept 14 days; uploaded input files are deleted after 24 hours. Download results at once; re-upload references if a run is resumed a day later | Kie task details, Kie file upload | Official |
| Images and audio go in as URLs. Upload with `POST /api/file-stream-upload` (form fields `file`, `uploadPath`, `fileName`); use `data.downloadUrl` from the reply | Kie file upload | Official |
| Failed tasks report `creditsConsumed: 0` | Kie Nano Banana, Kie Kling Avatar (callback examples) | Official |

Measured in the smoke test on 16 Nov 2026:
- Uploads go to `kieai.redpandaai.co` and come back as `tempfile.redpandaai.co` URLs.
- A Nano Banana 2.1 image at 2K costs 6 credits ($0.03).
- A Veo 3.1 Fast clip at 720p costs a flat 60 credits ($0.30), the same for 4 s and 6 s.
- Veo returns 720x1280, 24 fps, H.264 with AAC 48 kHz stereo, and accepts an AI-generated
  face as the first frame.
- For every task, the balance drop equalled Kie's `creditsConsumed`.

- Kling AI Avatar Standard costs about 10.2 credits ($0.051) per second of audio and returns
  720x1280 at 30 fps with 44.1 kHz audio, so it must be normalized to 24 fps and 48 kHz.
- ElevenLabs: the voice changer keeps word timing within 0.04 s; it can garble a name
  ("Rohan" became "Roman"). On one Hinglish line, `eleven_v4` made no word errors with a
  library voice or a cloned voice; `eleven_v3` made one with the library voice. v4 speaks
  about 20% slower. Scribe writes Hindi words in Devanagari and names in Roman letters.
- Gemini is **not usable as a face check**. Both `google/gemini-3.1-flash-lite` and the
  stronger `google/gemini-3.8-flash` failed the control: Flash Lite scored a
  wrong pairing (one persona's sheet against another persona's keyframe) as the same
  person, 5 out of 5, and 3.8 Flash scored both wrong pairings 5 and 4. Flash Lite's clip rubric gave low scores to both clips but missed a bottle
  that vanishes; treat its notes as hints, not facts.

- The local face check (`adgen/faces.py`, insightface `buffalo_sc` models, 15 MB) does tell
  the two personas apart, but only relatively. Over 14 clip frames, every frame scored
  higher against its own persona than against the other one, for both the sheet and the
  keyframe. A fixed limit alone does not work: a wrong pairing scored up to 0.52, while a
  true pair in a wide shot scored 0.38.
- Keyframes scored 0.64 to 0.72 against their own sheet. Clip frames scored 0.53 to 0.94
  against their own keyframe while the person faced the camera, and fell to 0.35 once she
  turned away at the end of the skincare clip.
- The two personas are too alike: their front views scored 0.66 against each other.


Measured on 17 Nov 2026:
- A Veo 3.1 Lite clip costs a flat 30 credits ($0.15) for 6 s, half the price of Fast. In a
  side-by-side of the same shot the frames were comparable (the Lite clip used the newer
  dry-voice prompt, so the sound is not a like-for-like comparison).
- ElevenLabs Voice Isolator kept every word of a Veo line and its timing (the last word ended
  0.06 s later). It removes all room sound: the quiet parts fell from about -37 dB to
  silence, so a room-tone bed has to be added back afterwards.
- Character sheets of four different personas scored 0.08 to 0.18 against each other, far
  under the 0.45 limit. The two personas that looked alike had scored 0.66.

Still open: Veo 8 s price; face limits need more data than a few personas and clips.

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
| One speaker per clip; speaking shots use a static or light handheld camera. The speaker is "turned toward the camera" only when a beat's eye-line is the lens | our rule | Practitioner |
| Speaking shots ask for a close, dry voice ("recorded close to the phone mic, dry intimate voice, small furnished room, no echo or reverb") and carry no "Ambient noise" line; naming a room tone made the voice echo | our rule, from reviewing the smoke test clips (17 Nov 2026) | Practitioner |
| The brand colour is named only in shots that show the product | our rule | Practitioner |
| Veo 3.1 Lite is the default tier for every clip | our choice (cost) | Practitioner |
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
| `eleven_v4` is our TTS default. ElevenLabs recommends it over v3 for Voice Library voices and professional clones, and in our test v3 sounded bad on a library voice | ElevenLabs v3 (advice), our smoke test | Official + practitioner |
| The voice changer is not used. In the smoke test its result sounded bad, added a loud click and garbled a name; the code is kept but marked unused | our smoke test (17 Nov 2026) | Practitioner |
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
| A new on-screen persona must differ from personas used for other brands: another name and at most 30% of the same look words. This is a first filter only; two different descriptions still produced near-identical faces. Character sheets of different personas must score under 0.45 against each other on the face check | Code (`adgen/casting.py`, `PERSONA_FACE_MAX` in `adgen/qa.py`); the sheet check is wired in at phase 5 |
| Critic notes are at most two plain sentences per field; any word count they state must equal the real one | Code |
| Every cast member is seen or heard in at least one shot | Code |
| No fast hand-on-object impacts (banging, slamming, hitting) in any beat | Code |
| At most one object-in-hand action per shot | Prompt, critic |
| For app products the screen is drawn in code from the brief (`app_screen`) and used as the product reference, described as a screen and not as a label | Code |
| Natural speech: contractions, short sentences, at most one filler or self-correction per ad | Prompt, critic |
| No emotion-only directions; shots that depend on micro-expressions are flagged | Prompt, critic |
| No action carried across a cut: each shot opens on a settled pose | Prompt, critic |

## Quality checks (phase 5; thresholds are tuned on our own smoke test data)

| Check | Rule | Status |
| --- | --- | --- |
| Words | Scribe transcript against the script: word error rate above 10% fails, and so does a missing last word. A failed clip gets one more take, then the shot is flagged | Built (`check_clip` in `adgen/pipeline.py`) |
| Trims | A spoken clip is cut to its words plus 0.15 s at each end, by code | Built (`build_edit_list` in `adgen/editor.py`) |
| Voice match | A speaker's clips may differ in median pitch by at most 10% | Built (`adgen/voice.py`); a warning only, there is no automatic fix |
| Final video | Picture and sound the same length, -14 LUFS give or take 1, no black or silent gaps before the end card | Built (`final_checks` in `adgen/editor.py`) |
| Clip rubric | Gemini scores 1 to 5 for hands, label, lip sync, "AI look" and hook strength; any score below 3 is re-rolled | Built (`look_at` in `adgen/providers/openrouter.py`); first results were not reliable enough to act on alone |
| Stray text | OCR on the first, middle and last frame of every clip; any unplanned text fails | Not built: needs an OCR library, size to be approved first |
| Face | A keyframe scores at least 0.58 against its character sheet; a clip frame scores at least 0.50 against the shot's keyframe; and in both cases higher than against any other persona | Built (`adgen/faces.py`, rule in `adgen/qa.py`); limits are provisional. Gemini failed this check |
