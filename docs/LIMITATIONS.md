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
