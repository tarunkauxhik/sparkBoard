# Limitations

Work in progress. This note grows as the system is built; the full version comes with the final samples.

- **Face check models are non-commercial.** The local face check (`adgen/faces.py`) uses the insightface
  `buffalo_sc` models, which are released for non-commercial research use only. A commercial version of
  this system would need a licensed face model.
- **Face limits are provisional.** They were set from 2 personas and 3 clips.
- **Voices are Veo's own.** The voice changer was dropped after testing (clicks and a garbled name), so a
  character's voice can differ between clips. This is not yet checked or fixed automatically.
- **Kling Avatar is a documented fallback only.** In testing its speaker turned away from the camera and
  the lip-sync was off, so no sample uses it.
- **Text on screens and labels.** Image models garble small text. App screens are drawn in code and passed
  as a reference, and dates or prices are left blank for code to add; reading the result back with OCR is
  not built yet.
