"""OpenRouter: the LLM calls (Claude Sonnet for writing; Gemini Flash for reviews from phase 5).

Cost safety, in order:
1. Prices are read from OpenRouter's models list (a free call), never guessed.
2. Before each call, the worst case (every input byte as a token + max_tokens of output)
   is checked against the cap.
3. After each call, the real cost from OpenRouter's usage data is recorded.
4. A call that times out is recorded at its worst case, because it may have been billed.
5. HTTP retries are only for 429 and 5xx (not billed), at most 2, with a pause between.
"""
import json
import time
from pathlib import Path

import httpx

from adgen.brain import TASKS, build_messages
from adgen.ledger import Ledger

API = "https://openrouter.ai/api/v1"
SONNET = "anthropic/claude-sonnet-5.5"
SEED = 7
HTTP_RETRIES = 2
BACKOFF_S = (2, 6)


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
        try:
            reply = self._post(body)
        except httpx.HTTPError as error:  # timeout or dropped connection: we cannot know if it was billed
            self.ledger.record("openrouter", f"sonnet:{task} (no reply, worst case)", worst_cost)
            self._save_log(task, {**log, "error": repr(error), "cost": worst_cost})
            raise LLMError(f"{task}: no reply from OpenRouter ({error!r}); counted as ${worst_cost:.3f}")
        cost = self._cost(reply)
        self.ledger.record("openrouter", f"sonnet:{task}", cost)
        self._save_log(task, {**log, "cost": cost, "response": reply})

        if "error" in reply:
            raise LLMError(f"{task}: OpenRouter error: {reply['error']}")
        choice = reply["choices"][0]
        if choice.get("finish_reason") == "length":
            raise LLMError(f"{task}: the reply hit max_tokens ({spec.max_tokens}) and was cut off")
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
