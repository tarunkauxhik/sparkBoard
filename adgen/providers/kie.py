"""Kie AI (Veo 3.1, Nano Banana 2.1, Kling Avatar).

Only the request builders exist so far; the HTTP calls arrive with the smoke test (phase 4).
Field names and values were checked against docs.kie.ai on 16 Nov 2026 (see docs/PROMPTING.md).

All three models share one endpoint: POST https://api.kie.ai/api/v1/jobs/createTask,
then GET /api/v1/jobs/recordInfo?taskId=... until `state` is "success" or "fail".
Neither Veo nor Nano Banana has a seed field on Kie: a re-roll is simply a new task.
We leave out `watermark` (we want none) and `callBackUrl` (we poll; we have no public URL).
"""

VEO_TIERS = ("veo3_fast", "veo3_lite")
MAX_REFERENCE_IMAGES = 10


def veo_payload(prompt: str, first_frame_url: str, tier: str, duration_s: int) -> dict:
    """One Veo 3.1 clip that starts from a keyframe (first-frame mode), 9:16, 720p."""
    if tier not in VEO_TIERS:
        raise ValueError(f"unknown Veo tier {tier!r}")
    if duration_s not in (4, 6, 8):
        raise ValueError("Veo clips are 4, 6 or 8 seconds")
    return {
        "model": "veo-3-1",
        "input": {
            "model": tier,
            "prompt": prompt,
            "image_urls": [first_frame_url],
            "generation_type": "FIRST_AND_LAST_FRAMES_2_VIDEO",
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "duration": duration_s,
            # Always sent as false: otherwise Hindi dialogue gets translated to English.
            "enable_translation": False,
        },
    }


def nano_banana_payload(prompt: str, reference_urls: list[str], aspect_ratio: str = "9:16") -> dict:
    """One Nano Banana 2.1 image at 2K. The prompt refers to the references as image 1, 2, ..."""
    if len(reference_urls) > MAX_REFERENCE_IMAGES:
        raise ValueError(f"Nano Banana takes at most {MAX_REFERENCE_IMAGES} reference images")
    return {
        "model": "nano-banana-2-1",
        "input": {
            "prompt": prompt,
            "image_input": reference_urls,
            "aspect_ratio": aspect_ratio,
            "resolution": "2K",
            "output_format": "png",
        },
    }


def kling_avatar_payload(prompt: str, image_url: str, audio_url: str) -> dict:
    """Kling AI Avatar Standard (720p): makes the keyframe speak the given audio.
    The clip is as long as the audio. The prompt describes expression and movement only."""
    return {
        "model": "kling/ai-avatar-standard",
        "input": {"image_url": image_url, "audio_url": audio_url, "prompt": prompt},
    }
