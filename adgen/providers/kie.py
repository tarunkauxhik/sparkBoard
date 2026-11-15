"""Kie AI (Veo, Nano Banana, Kling Avatar).

Only the request builder exists so far; the HTTP calls arrive with the smoke test (phase 4).
Checked against docs.kie.ai on 15 Nov 2026: POST /api/v1/jobs/createTask.
"""

VEO_TIERS = ("veo3_fast", "veo3_lite")


def veo_payload(prompt: str, image_urls: list[str], tier: str, duration_s: int) -> dict:
    """Request body for one Veo 3.1 clip that starts from a keyframe."""
    if tier not in VEO_TIERS:
        raise ValueError(f"unknown Veo tier {tier!r}")
    if duration_s not in (4, 6, 8):
        raise ValueError("Veo clips are 4, 6 or 8 seconds")
    return {
        "model": "veo-3-1",
        "input": {
            "model": tier,
            "prompt": prompt,
            "image_urls": image_urls,
            "generation_type": "FIRST_AND_LAST_FRAMES_2_VIDEO",
            "aspect_ratio": "9:16",
            "duration": str(duration_s),
            # Always sent as false: otherwise Hindi dialogue gets translated to English.
            "enable_translation": False,
        },
    }
