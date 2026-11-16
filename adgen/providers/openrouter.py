"""OpenRouter: the LLM calls (Claude Sonnet for writing; Gemini Flash for reviews from phase 5).

Cost safety, in order:
1. Prices are read from OpenRouter's models list (a free call), never guessed.
2. Before each call, the worst case (every input byte as a token + max_tokens of output)
   is checked against the cap.
3. After each call, the real cost from OpenRouter's usage data is recorded.
4. A call that times out is recorded at its worst case, because it may have been billed.
5. HTTP retries are only for 429 and 5xx (not billed), at most 2, with a pause between.
"""
import base64
import json
import time
from pathlib import Path

import httpx
from pydantic import BaseModel

from adgen.brain import TASKS, build_messages
from adgen.ledger import Ledger

API = "https://openrouter.ai/api/v1"
SONNET = "anthropic/claude-sonnet-5.5"
GEMINI = "google/gemini-3.1-flash-lite"  # the cheapest current Flash with video input (16 Nov 2026)
SEED = 7
HTTP_RETRIES = 2
BACKOFF_S = (2, 6)


# Upper bounds for the cap check on media. Gemini bills roughly 258 tokens per image tile and
# about 300 tokens per second of video; these are set well above that.
IMAGE_TOKENS_MAX, VIDEO_TOKENS_PER_S_MAX = 3000, 1000


def _data_url(path: Path, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


class LLMError(RuntimeError):
    """The call failed in a way that another try with the same prompt will not fix."""


class OpenRouter:
    def __init__(self, ledger: Ledger, log_dir: Path, api_key: str, model: str = SONNET,
                 client: httpx.Client | None = None, sleep=time.sleep):
        self.ledger, self.log_dir, self.model, self.sleep = ledger, log_dir, model, sleep
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.client = client or httpx.Client(timeout=httpx.Timeout(180, connect=15))
        models = self.client.get(f"{API}/models").json()["data"]
        info = next((m for m in models if m["id"] == model), None)
        if info is None:
            raise LLMError(f"model {model!r} is not in OpenRouter's models list")
        self.price_in = float(info["pricing"]["prompt"])       # USD per input token
        self.price_out = float(info["pricing"]["completion"])  # USD per output token
        # Some models ignore temperature and seed. We still send them, and log whether they count.
        self.sampling_supported = "temperature" in info.get("supported_parameters", [])

    def chat_json(self, task: str, ctx: dict, feedback: str = "") -> dict:
        """Run one LLM task and return its reply as a dict (not yet validated)."""
        spec = TASKS[task]
        system, user = build_messages(task, ctx, feedback)
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": spec.max_tokens,
            "temperature": spec.temperature,
            "seed": SEED,
            "reasoning": {"effort": spec.reasoning},
            "usage": {"include": True},
        }
        # A token is at least one byte, so the byte count is a true upper bound on input tokens.
        worst_cost = len((system + user).encode()) * self.price_in + spec.max_tokens * self.price_out
        self.ledger.check("openrouter", worst_cost)

        log = {"task": task, "model": self.model, "temperature": spec.temperature, "seed": SEED,
               "sampling_params_supported": self.sampling_supported, "max_tokens": spec.max_tokens,
               "worst_cost": round(worst_cost, 5), "request": body}
        return self._send(task, body, worst_cost, log)

    def look_at(self, name: str, instructions: str, schema: type[BaseModel], images: list[Path] = (),
                video: Path | None = None, video_seconds: float = 0, max_tokens: int = 1000) -> BaseModel:
        """Show the model images and/or one video and get back a validated review.
        Send small copies (about 1024 px images, a 480p clip): reviews do not need full size."""
        text = (f"{instructions}\n\nReply with one JSON object only, no markdown fences, matching this "
                f"schema:\n{json.dumps(schema.model_json_schema())}")
        media = [{"type": "image_url", "image_url": {"url": _data_url(image, "image/jpeg")}} for image in images]
        if video:
            media.append({"type": "video_url", "video_url": {"url": _data_url(video, "video/mp4")}})
        body = {"model": self.model, "max_tokens": max_tokens, "temperature": 0.2, "usage": {"include": True},
                "messages": [{"role": "user", "content": [{"type": "text", "text": text}, *media]}]}
        input_tokens = len(text.encode()) + IMAGE_TOKENS_MAX * len(images) + VIDEO_TOKENS_PER_S_MAX * video_seconds
        worst_cost = input_tokens * self.price_in + max_tokens * self.price_out
        self.ledger.check("openrouter", worst_cost)
        # The log names the files instead of holding megabytes of base64.
        log = {"task": name, "model": self.model, "max_tokens": max_tokens, "worst_cost": round(worst_cost, 5),
               "request": {"text": text, "images": [image.name for image in images],
                           "video": video.name if video else None}}
        return schema.model_validate(self._send(name, body, worst_cost, log))

    def _send(self, task: str, body: dict, worst_cost: float, log: dict) -> dict:
        """Send one request, record its real cost, save its log and return the reply as a dict."""
        label = f"{self.model.split('/')[-1]}:{task}"
        try:
            reply = self._post(body)
        except httpx.HTTPError as error:  # timeout or dropped connection: we cannot know if it was billed
            self.ledger.record("openrouter", f"{label} (no reply, worst case)", worst_cost)
            self._save_log(task, {**log, "error": repr(error), "cost": worst_cost})
            raise LLMError(f"{task}: no reply from OpenRouter ({error!r}); counted as ${worst_cost:.3f}")
        cost = self._cost(reply)
        self.ledger.record("openrouter", label, cost)
        self._save_log(task, {**log, "cost": cost, "response": reply})

        if "error" in reply:
            raise LLMError(f"{task}: OpenRouter error: {reply['error']}")
        choice = reply["choices"][0]
        if choice.get("finish_reason") == "length":
            raise LLMError(f"{task}: the reply hit max_tokens ({body['max_tokens']}) and was cut off")
        text = choice["message"]["content"] or ""
        try:
            # strict=False: models sometimes put a raw line break inside a string
            return json.loads(text[text.find("{"): text.rfind("}") + 1], strict=False)
        except json.JSONDecodeError as error:
            raise ValueError(f"the reply was not valid JSON: {error}")  # the pipeline may retry this

    def _post(self, body: dict) -> dict:
        """POST with at most HTTP_RETRIES retries, only on 429 and 5xx (which are not billed)."""
        for attempt in range(HTTP_RETRIES + 1):
            response = self.client.post(f"{API}/chat/completions", headers=self.headers, json=body)
            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError:  # a broken 200 body may still have been billed
                    raise httpx.DecodingError("OpenRouter sent a 200 reply that is not JSON")
            retryable = response.status_code == 429 or response.status_code >= 500
            if not retryable or attempt == HTTP_RETRIES:
                raise LLMError(f"OpenRouter HTTP {response.status_code}: {response.text[:300]}")
            self.sleep(BACKOFF_S[attempt])

    def _cost(self, reply: dict) -> float:
        """Real cost in USD from the usage data; falls back to token counts times price."""
        usage = reply.get("usage") or {}
        if usage.get("cost") is not None:
            return float(usage["cost"])
        return (usage.get("prompt_tokens", 0) * self.price_in
                + usage.get("completion_tokens", 0) * self.price_out)

    def _save_log(self, task: str, log: dict) -> None:
        """One file per call in llm/, for debugging. Bodies only: no headers, so no key."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        number = len(list(self.log_dir.glob("*.json"))) + 1
        path = self.log_dir / f"{number:02d}_{task}.json"
        path.write_text(json.dumps(log, ensure_ascii=False, indent=1), "utf-8")
