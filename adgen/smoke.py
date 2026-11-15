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

from adgen.prompts import character_sheet_prompt, keyframe_request, packshot_prompt
from adgen.providers.kie import ASSUMED_IMAGE_USD, USD_PER_CREDIT, Kie, nano_banana_payload
from adgen.schemas import Brief, Look, Refs, Storyboard

SAMPLE = Path("samples/skincare")  # the reviewed storyboard the smoke test draws from


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
    brief = Brief.model_validate_json((SAMPLE / "brief.json").read_text("utf-8"))
    look = Look.model_validate_json((SAMPLE / "look.json").read_text("utf-8"))
    board = Storyboard.model_validate_json((SAMPLE / "storyboard.json").read_text("utf-8"))
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


def _image(kie: Kie, out: Path, prompt: str, reference_urls: list[str], aspect_ratio: str) -> None:
    if out.exists():
        print(f"have  {out.name}")
        return
    log = kie.run_task(out.stem, nano_banana_payload(prompt, reference_urls, aspect_ratio), ASSUMED_IMAGE_USD, out)
    print(f"done  {out.name}: {log['credits_used']:g} credits = ${log['cost_usd']:.3f} "
          f"(Kie reports creditsConsumed {log['credits_consumed']}; balance {log['credits_before']:g} -> "
          f"{log['credits_after']:g})")


STEPS = {"a": step_a, "b": step_b}
