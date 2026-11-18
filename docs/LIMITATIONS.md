# Limitations

Work in progress. This note grows as the system is built; the full version comes with the final samples.

- **Face check models are non-commercial.** The local face check (`adgen/faces.py`) uses the insightface
  `buffalo_sc` models, which are released for non-commercial research use only. A commercial version of
  this system would need a licensed face model.
- **Face limits are provisional.** They were set from 2 personas and 3 clips.
- **Voices are Veo's own.** The voice changer was dropped after testing (clicks and a garbled name), so a
  character's voice can differ between clips. A pitch check flags it; nothing fixes it automatically.
- **Kling Avatar is a documented fallback only.** In testing its speaker turned away from the camera and
  the lip-sync was off, so no sample uses it.
- **Text on screens and labels.** Image models garble small text. App screens are drawn in code and passed
  as a reference. Dates or prices are left blank by the image model and written into the keyframe by code,
  where Gemini finds the blank label; Veo then animates that frame and may still blur the text. The text is
  drawn flat, without following the label's angle. Reading the result back with OCR is not built: the
  smallest local OCR library needs OpenCV, about 65 MB to download.
- **No music bed yet.** The ads carry speech and a quiet room tone only.
- **One speaker can sound like different people.** Veo gives every clip its own voice. A pitch
  check flags it: meera's clips are 15% apart, kabir's 71% (partly his theatrical first line).
  Off-screen narrators are one ElevenLabs voice and do not have this problem.
- **Faces drift when people turn away.** A clip starts on the right face (its keyframe) but can
  change as the person turns or looks down; the coffee sample's opening shot is flagged for it.
  Every shot gets two takes, then it is flagged rather than retried forever.
- **Faces turned away score low.** The local face model scores the right person at 0.36 to 0.52
  when they look down or are side-lit, against 0.62 to 0.75 face-on. The keyframe limit (0.45)
  was set from these few runs and needs more data.
- **The click check cannot tell a planned sound from a stray one.** In the earbuds ad the drilling
  the story asks for is flagged as taps.
- **Ads come out shorter than planned.** Spoken clips are cut to their words plus 0.4 s, so a
  storyboard planned at 12 to 22 s gives a 9 to 18 s ad.
- **Kie can fail and be slow.** Its Veo service returned "Internal Error" on 4 of about 25 clip
  tasks (free; the pipeline retries) and one clip waited 40 minutes in its queue.
- **The Gemini review is only a hint.** It reliably notices warped hands and faces that change, but
  it also reports things that are not there; it never passes or fails an ad.
