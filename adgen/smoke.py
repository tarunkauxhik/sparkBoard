"""Smoke test: the fewest paid calls that answer the open questions, one step at a time.

Each step keeps its outputs in one folder (runs/smoke-<date>/): the media, a tasks/ folder
with every prompt, task ID, credit balance and cost, and the cost ledger.
A step that already has its output file skips that task, so steps can be run again safely.
"""
import json
import os
import time
from pathlib import Path

import httpx
from PIL import Image

from adgen.prompts import character_sheet_prompt, keyframe_request, motion_prompt, packshot_prompt
from adgen.providers.kie import (
    ASSUMED_IMAGE_USD, ASSUMED_VEO_USD_PER_S, USD_PER_CREDIT, Kie, nano_banana_payload, veo_payload,
)
from adgen.schemas import Brief, Look, Refs, Storyboard

SAMPLES = Path("samples")  # the reviewed storyboards the smoke test draws from


def _sample(name: str) -> tuple[Brief, Look, Storyboard]:
    folder = SAMPLES / name
    return (Brief.model_validate_json((folder / "brief.json").read_text("utf-8")),
            Look.model_validate_json((folder / "look.json").read_text("utf-8")),
            Storyboard.model_validate_json((folder / "storyboard.json").read_text("utf-8")))


def _report(log: dict, name: str) -> None:
    print(f"done  {name}: {log['credits_used']:g} credits = ${log['cost_usd']:.3f} "
          f"(Kie reports creditsConsumed {log['credits_consumed']}; balance {log['credits_before']:g} -> "
          f"{log['credits_after']:g})")


def _image(kie: Kie, out: Path, prompt: str, reference_urls: list[str], aspect_ratio: str) -> None:
    if out.exists():
        print(f"have  {out.name}")
        return
    _report(kie.run_task(out.stem, nano_banana_payload(prompt, reference_urls, aspect_ratio),
                         ASSUMED_IMAGE_USD, out), out.name)


def step_a(kie: Kie, folder: Path) -> None:
    """Free checks: Kie balance, one upload, ElevenLabs usage."""
    credits = kie.credits()
    print(f"Kie balance: {credits:g} credits (about ${credits * USD_PER_CREDIT:.2f} at ${USD_PER_CREDIT}/credit)")

    probe = folder / "upload_probe.png"
    Image.new("RGB", (64, 64), "#6b8f76").save(probe)
    url = kie.upload(probe)
    reachable = httpx.get(url, timeout=60).status_code
    print(f"Kie upload: OK, host {httpx.URL(url).host}, file reachable: HTTP {reachable}")

    now = int(time.time() * 1000)
    usage = httpx.get("https://api.elevenlabs.io/v1/usage/character-stats", timeout=60,
                      headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
                      params={"start_unix": now - 30 * 86400 * 1000, "end_unix": now,
                              "breakdown_type": "product_type"}).json()
    used = {product: round(sum(values)) for product, values in usage.get("usage", {}).items()}
    print(f"ElevenLabs credits used in the last 30 days: {used}")
    (folder / "step_a.json").write_text(json.dumps(
        {"kie_credits": credits, "upload_host": httpx.URL(url).host, "upload_reachable": reachable,
         "elevenlabs_credits_used_30d": used}, indent=1), "utf-8")


def step_b(kie: Kie, folder: Path) -> None:
    """Three images: meera's character sheet, the product packshot, and the keyframe of shot 1."""
    brief, look, board = _sample("skincare")
    shot = board.shots[0]
    who = next(member for member in look.cast if member.name == shot.character)

    sheet, packshot, keyframe = (folder / f"sheet_{who.name}.png", folder / "packshot.png",
                                 folder / f"keyframe_{shot.id}.png")
    _image(kie, sheet, character_sheet_prompt(who), [], "16:9")
    _image(kie, packshot, packshot_prompt(brief), [], "1:1")
    # The keyframe prompt names its reference images in order, so they are uploaded in that order.
    prompt, references = keyframe_request(shot, look, brief,
                                          Refs(characters={who.name: str(sheet)}, product=[str(packshot)]))
    if not keyframe.exists():
        urls = [kie.upload(Path(reference)) for reference in references]
        _image(kie, keyframe, prompt, urls, "9:16")


def step_c(kie: Kie, folder: Path) -> None:
    """One Veo Fast clip in English: skincare shot 1, starting from its keyframe."""
    brief, look, board = _sample("skincare")
    shot = board.shots[0]
    keyframe, clip = folder / f"keyframe_{shot.id}.png", folder / f"clip_{shot.id}_take1.mp4"
    if clip.exists():
        print(f"have  {clip.name}")
        return
    payload = veo_payload(motion_prompt(shot, look, brief), kie.upload(keyframe), "veo3_fast", shot.duration_s)
    _report(kie.run_task(clip.stem, payload, ASSUMED_VEO_USD_PER_S * shot.duration_s, clip), clip.name)


STEPS = {"a": step_a, "b": step_b, "c": step_c}
