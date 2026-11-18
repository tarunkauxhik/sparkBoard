"""Kie task client, tested against a fake HTTP server. No real calls."""
import json

import httpx
import pytest

from adgen.ledger import BudgetExceeded, Ledger
from adgen.providers.kie import Kie, KieError, nano_banana_payload

PAYLOAD = nano_banana_payload("a prompt", [])


class FakeKie:
    """A tiny stand-in for Kie: a credit balance, one task, and a result file."""

    def __init__(self, states=("generating", "success"), price=6, create_code=200):
        self.credits, self.states, self.price, self.create_code = 2000.0, list(states), price, create_code
        self.created = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/chat/credit"):
            return httpx.Response(200, json={"code": 200, "data": self.credits})
        if path.endswith("/createTask"):
            if self.create_code != 200:
                return httpx.Response(200, json={"code": self.create_code, "msg": "insufficient credits"})
            self.created += 1
            return httpx.Response(200, json={"code": 200, "data": {"taskId": "task_1"}})
        if path.endswith("/recordInfo"):
            state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
            data = {"taskId": "task_1", "state": state}
            if state == "success":
                self.credits -= self.price
                data |= {"creditsConsumed": self.price,
                         "resultJson": json.dumps({"resultUrls": ["https://files.example/out.png"]})}
            if state == "fail":
                data |= {"creditsConsumed": 0, "failCode": "501", "failMsg": "blocked by safety filter"}
            return httpx.Response(200, json={"code": 200, "data": data})
        if path.endswith("/file-stream-upload"):
            return httpx.Response(200, json={"code": 200, "data": {"downloadUrl": "https://files.example/in.png"}})
        return httpx.Response(200, content=b"PNG-BYTES")  # the result download


def make(tmp_path, fake, cap=1.00, clock=None):
    ledger = Ledger(tmp_path / "ledger.jsonl", {"kie": cap})
    client = httpx.Client(transport=httpx.MockTransport(fake))
    kie = Kie(ledger, tmp_path / "tasks", "secret-test-key", client=client, sleep=lambda s: None,
              **({"clock": clock} if clock else {}))
    return kie, ledger


def test_a_task_is_created_polled_downloaded_and_costed_from_the_balance(tmp_path):
    fake = FakeKie()
    kie, ledger = make(tmp_path, fake)
    log = kie.run_task("sheet", PAYLOAD, 0.10, tmp_path / "sheet.png")
    assert (tmp_path / "sheet.png").read_bytes() == b"PNG-BYTES"
    assert (log["credits_before"], log["credits_after"], log["credits_used"], log["credits_consumed"]) == (2000, 1994, 6, 6)
    assert ledger.spent("kie") == pytest.approx(0.03)  # 6 credits at $0.005, not the assumed $0.10
    saved = (tmp_path / "tasks/sheet.json").read_text("utf-8")
    assert '"task_id": "task_1"' in saved and "secret-test-key" not in saved


def test_the_cap_check_uses_the_assumed_price_before_any_call(tmp_path):
    fake = FakeKie()
    kie, ledger = make(tmp_path, fake, cap=0.05)
    with pytest.raises(BudgetExceeded):
        kie.run_task("sheet", PAYLOAD, 0.10, tmp_path / "sheet.png")
    assert fake.created == 0 and ledger.total() == 0


def test_a_failure_code_in_an_http_200_reply_is_an_error(tmp_path):
    fake = FakeKie(create_code=402)
    kie, ledger = make(tmp_path, fake)
    with pytest.raises(KieError, match="402"):
        kie.run_task("sheet", PAYLOAD, 0.10, tmp_path / "sheet.png")
    assert ledger.total() == 0 and not (tmp_path / "tasks/sheet.json").exists()  # nothing was created


def test_a_slow_task_is_never_resubmitted(tmp_path):
    fake = FakeKie(states=("generating",))
    ticks = iter(range(0, 10**6, 600))  # every look at the clock is 10 minutes later
    kie, ledger = make(tmp_path, fake, clock=lambda: next(ticks))
    with pytest.raises(KieError, match="Never resubmit"):
        kie.run_task("clip", PAYLOAD, 0.50, tmp_path / "clip.mp4")
    assert json.loads((tmp_path / "tasks/clip.json").read_text("utf-8"))["task_id"] == "task_1"

    fake.states = ["success"]  # later the task finishes; running the step again picks it up
    kie.run_task("clip", PAYLOAD, 0.50, tmp_path / "clip.mp4")
    assert fake.created == 1 and (tmp_path / "clip.mp4").exists()
    assert ledger.spent("kie") == pytest.approx(0.03)


def test_a_failed_task_costs_what_the_balance_says(tmp_path):
    fake = FakeKie(states=("fail",))
    kie, ledger = make(tmp_path, fake)
    with pytest.raises(KieError, match="safety filter"):
        kie.run_task("clip", PAYLOAD, 0.50, tmp_path / "clip.mp4")
    assert ledger.spent("kie") == 0 and not (tmp_path / "clip.mp4").exists()


def test_upload_returns_the_file_url_and_outputs_are_never_overwritten(tmp_path):
    kie, _ = make(tmp_path, FakeKie())
    source = tmp_path / "in.png"
    source.write_bytes(b"x")
    assert kie.upload(source) == "https://files.example/in.png"
    with pytest.raises(FileExistsError):
        kie.run_task("in", PAYLOAD, 0.10, source)


def test_the_cost_is_kies_own_figure_when_someone_else_uses_the_shared_account(tmp_path):
    fake = FakeKie()

    class Busy(FakeKie):
        def __call__(self, request):
            response = fake(request)
            if request.url.path.endswith("/recordInfo"):
                fake.credits -= 36  # another person's task finishes on the same account meanwhile
            return response

    kie, ledger = make(tmp_path, Busy())
    log = kie.run_task("sheet", PAYLOAD, 0.10, tmp_path / "sheet.png")
    assert log["credits_used"] > 6 and log["credits_consumed"] == 6
    assert ledger.spent("kie") == pytest.approx(0.03)  # 6 credits, not the balance change
