"""Kie AI (Veo 3.1, Nano Banana 2.1, Kling Avatar): request builders and the task client.

Field names and values were checked against docs.kie.ai on 16 Nov 2026 (see docs/PROMPTING.md).
All three models share one flow: POST /jobs/createTask, then GET /jobs/recordInfo until
`state` is "success" or "fail", then download the result (Kie keeps it for 14 days).
Neither Veo nor Nano Banana has a seed field on Kie: a re-roll is simply a new task.
We leave out `watermark` (we want none) and `callBackUrl` (we poll; we have no public URL).

Cost safety:
1. Before a task, an assumed high price is checked against the cap.
2. The task ID is saved to disk before polling. A task with a saved ID is never submitted
   again: running the step again just keeps waiting for it.
3. The credit balance is read before and after every task. The ledger records Kie's own
   `creditsConsumed` for the task (the balance change is used only if Kie gives none), because
   the account is shared and its balance also moves for other people's tasks. Both go in the log.
"""
import json
import time
from pathlib import Path

import httpx

from adgen.ledger import Ledger

API = "https://api.kie.ai/api/v1"
UPLOAD_URL = "https://kieai.redpandaai.co/api/file-stream-upload"
USD_PER_CREDIT = 0.005
# Prices assumed for the cap check: the real prices measured in the smoke test (16 Nov 2026)
# plus a margin. Measured: a 2K Nano Banana image is 6 credits ($0.03); a Veo Fast clip is a
# flat 60 credits ($0.30) for both 4 s and 6 s. Veo Lite and Kling Avatar are not measured yet.
ASSUMED_IMAGE_USD = 0.03          # measured on 10 images, always 6 credits
ASSUMED_VEO_CLIP_USD = {"veo3_fast": 0.40, "veo3_lite": 0.20}  # Fast measured at 0.30; Lite listed at 0.15
ASSUMED_AVATAR_USD_PER_S = 0.10
POLL_START_S, POLL_SLOWEST_S, POLL_TIMEOUT_S = 3, 15, 20 * 60

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


class KieError(RuntimeError):
    pass


class Kie:
    def __init__(self, ledger: Ledger, task_dir: Path, api_key: str,
                 client: httpx.Client | None = None, sleep=time.sleep, clock=time.monotonic):
        self.ledger, self.task_dir, self.sleep, self.clock = ledger, task_dir, sleep, clock
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.client = client or httpx.Client(timeout=60)
        task_dir.mkdir(parents=True, exist_ok=True)

    def _data(self, response: httpx.Response):
        """The `data` part of a Kie reply. Kie answers HTTP 200 even on failure, so check `code`."""
        body = response.json()
        if body.get("code") != 200:
            raise KieError(f"Kie code {body.get('code')}: {body.get('msg')}")
        return body.get("data")

    def credits(self) -> float:
        """Remaining credit balance. A free call."""
        return float(self._data(self.client.get(f"{API}/chat/credit", headers=self.headers)))

    def upload(self, path: Path, folder: str = "sparkboard") -> str:
        """Upload a local file and return its URL. Free; Kie deletes the file after 24 hours."""
        with path.open("rb") as file:
            response = self.client.post(UPLOAD_URL, headers=self.headers, files={"file": (path.name, file)},
                                        data={"uploadPath": folder, "fileName": path.name})
        return self._data(response)["downloadUrl"]

    def run_task(self, name: str, payload: dict, assumed_usd: float, out: Path) -> dict:
        """Create one task (or keep waiting for a saved one), download its result to `out`
        and record its real cost. Returns the task log, which is also saved in task_dir."""
        if out.exists():
            raise FileExistsError(f"refusing to overwrite {out}")
        log_path = self.task_dir / f"{name}.json"
        if log_path.exists():  # this task was already submitted: never submit it again
            log = json.loads(log_path.read_text("utf-8"))
        else:
            self.ledger.check("kie", assumed_usd)
            log = {"name": name, "payload": payload, "assumed_usd": assumed_usd,
                   "credits_before": self.credits()}
            try:
                created = self._data(self.client.post(f"{API}/jobs/createTask", headers=self.headers, json=payload))
            except httpx.HTTPError as error:  # no answer: the task may exist and may be billed
                self.ledger.record("kie", f"{name} (no reply to createTask, assumed price)", assumed_usd)
                raise KieError(f"{name}: no reply to createTask ({error!r}); counted as ${assumed_usd:.2f}")
            log["task_id"] = created["taskId"]
            self._save(log_path, log)  # the ID is on disk before the first poll

        if "state" not in log:
            detail = self._wait(log["task_id"])
            after = self.credits()
            used = round(log["credits_before"] - after, 4)
            # The account is shared: the balance can also drop for other people's tasks, so Kie's
            # own figure for this task is the cost; the balance change is kept in the log to compare.
            consumed = detail.get("creditsConsumed")
            credits = float(consumed) if consumed is not None else used
            log.update(state=detail["state"], credits_after=after, credits_used=used,
                       credits_consumed=consumed, cost_usd=round(credits * USD_PER_CREDIT, 5),
                       fail=f"{detail.get('failCode')}: {detail.get('failMsg')}" if detail["state"] == "fail" else "",
                       result_urls=json.loads(detail.get("resultJson") or "{}").get("resultUrls", []))
            self.ledger.record("kie", name, log["cost_usd"])
            self._save(log_path, log)
        if log["state"] == "fail":
            raise KieError(f"{name} failed: {log['fail']}")
        out.write_bytes(self.client.get(log["result_urls"][0]).content)
        return log

    def _wait(self, task_id: str) -> dict:
        """Poll until the task succeeds or fails. Reading is free and safe to repeat."""
        deadline, pause = self.clock() + POLL_TIMEOUT_S, POLL_START_S
        while True:
            try:
                detail = self._data(self.client.get(f"{API}/jobs/recordInfo", headers=self.headers,
                                                    params={"taskId": task_id}))
            except httpx.HTTPError:
                detail = None  # a dropped poll: just ask again
            if detail and detail.get("state") in ("success", "fail"):
                return detail
            if self.clock() > deadline:
                raise KieError(f"task {task_id} is still running after {POLL_TIMEOUT_S // 60} minutes. "
                               "Its ID is saved: run the step again to keep waiting. Never resubmit.")
            self.sleep(pause)
            pause = min(pause * 1.3, POLL_SLOWEST_S)

    def _save(self, path: Path, log: dict) -> None:
        path.write_text(json.dumps(log, ensure_ascii=False, indent=1), "utf-8")
