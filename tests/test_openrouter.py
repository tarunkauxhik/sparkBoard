"""OpenRouter cost safety, tested against a fake HTTP server. No real calls."""
import httpx
import pytest

from adgen.ledger import BudgetExceeded, Ledger
from adgen.providers.openrouter import SONNET, LLMError, OpenRouter

MODELS = {"data": [{"id": SONNET, "pricing": {"prompt": "0.000002", "completion": "0.00001"},
                    "supported_parameters": ["max_tokens"]}]}
CTX = {"brief": {"brand": "Dewline"}}


def reply(content='{"pains": []}', finish="stop", cost=0.0123):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": finish}],
                                     "usage": {"cost": cost}})


def make(tmp_path, handler, cap=1.00):
    """An OpenRouter provider wired to `handler`. Returns (provider, ledger, list of chat requests)."""
    posts = []

    def route(request: httpx.Request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json=MODELS)
        posts.append(request)
        return handler(len(posts))

    ledger = Ledger(tmp_path / "ledger.jsonl", {"openrouter": cap})
    client = httpx.Client(transport=httpx.MockTransport(route))
    provider = OpenRouter(ledger, tmp_path / "llm", "secret-test-key", client=client, sleep=lambda s: None)
    return provider, ledger, posts


def test_records_the_real_cost_and_logs_the_call_without_the_key(tmp_path):
    provider, ledger, posts = make(tmp_path, lambda n: reply())
    assert provider.chat_json("insights", CTX) == {"pains": []}
    assert ledger.spent("openrouter") == 0.0123
    log = (tmp_path / "llm/01_insights.json").read_text("utf-8")
    assert '"max_tokens": 2000' in log and '"response"' in log
    assert "secret-test-key" not in log


def test_refuses_before_sending_if_the_worst_case_could_pass_the_cap(tmp_path):
    provider, ledger, posts = make(tmp_path, lambda n: reply(), cap=0.01)  # 2000 tokens out = $0.02
    with pytest.raises(BudgetExceeded):
        provider.chat_json("insights", CTX)
    assert posts == [] and ledger.total() == 0


def test_retries_429_and_5xx_at_most_twice_and_they_cost_nothing(tmp_path):
    provider, ledger, posts = make(tmp_path, lambda n: httpx.Response(429) if n == 1 else reply())
    provider.chat_json("insights", CTX)
    assert len(posts) == 2

    provider, ledger, posts = make(tmp_path / "b", lambda n: httpx.Response(503, text="down"))
    with pytest.raises(LLMError, match="503"):
        provider.chat_json("insights", CTX)
    assert len(posts) == 3 and ledger.total() == 0


def test_a_timeout_is_not_retried_and_counts_as_the_worst_case(tmp_path):
    def timeout(n):
        raise httpx.ReadTimeout("too slow")

    provider, ledger, posts = make(tmp_path, timeout)
    with pytest.raises(LLMError, match="no reply"):
        provider.chat_json("insights", CTX)
    assert len(posts) == 1
    assert ledger.spent("openrouter") > 0.02  # at least max_tokens of output


def test_a_cut_off_reply_is_an_error_but_its_cost_is_recorded(tmp_path):
    provider, ledger, posts = make(tmp_path, lambda n: reply(finish="length"))
    with pytest.raises(LLMError, match="max_tokens"):
        provider.chat_json("insights", CTX)
    assert ledger.spent("openrouter") == 0.0123


def test_a_reply_that_is_not_json_can_be_retried_by_the_pipeline(tmp_path):
    provider, ledger, posts = make(tmp_path, lambda n: reply(content="Sure! Here you go."))
    with pytest.raises(ValueError, match="not valid JSON"):
        provider.chat_json("insights", CTX)
