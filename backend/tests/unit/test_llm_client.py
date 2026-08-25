import httpx
import pytest

from app.agents.llm import (
    LLMResponse,
    OpenRouterClient,
    StructuredOutputError,
)

SCHEMA = {
    "name": "emit_thing",
    "description": "emit a thing",
    "parameters": {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
    },
}


def _client(handler) -> OpenRouterClient:
    return OpenRouterClient(api_key="k", transport=httpx.MockTransport(handler))


def _completion(message: dict, finish: str = "stop") -> dict:
    return {
        "choices": [{"message": message, "finish_reason": finish}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cost": 0},
    }


async def test_chat_returns_content_and_usage():
    def handler(request):
        return httpx.Response(200, json=_completion({"role": "assistant", "content": "hi"}))

    r = await _client(handler).chat([{"role": "user", "content": "yo"}])
    assert isinstance(r, LLMResponse)
    assert r.content == "hi"
    assert r.usage.total_tokens == 15


async def test_reasoning_is_never_exposed():
    def handler(request):
        return httpx.Response(
            200,
            json=_completion(
                {"role": "assistant", "content": "answer", "reasoning": "SECRET CHAIN OF THOUGHT"}
            ),
        )

    r = await _client(handler).chat([{"role": "user", "content": "x"}])
    assert not hasattr(r, "reasoning")
    assert "SECRET" not in repr(r.content)


async def test_structured_uses_forced_tool_choice_not_response_format():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json=_completion(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "1",
                            "type": "function",
                            "function": {"name": "emit_thing", "arguments": '{"value":"ok"}'},
                        }
                    ],
                },
                finish="tool_calls",
            ),
        )

    data, usage = await _client(handler).structured([{"role": "user", "content": "go"}], SCHEMA)
    assert data == {"value": "ok"}
    # The verified platform fact: response_format does not work on this model.
    assert "response_format" not in seen
    assert seen["tool_choice"] == {"type": "function", "function": {"name": "emit_thing"}}


async def test_structured_retries_when_model_answers_in_prose():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            # Exactly the observed failure mode: a markdown table instead of JSON.
            return httpx.Response(
                200, json=_completion({"role": "assistant", "content": "| a | b |\n|---|---|"})
            )
        return httpx.Response(
            200,
            json=_completion(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "1",
                            "type": "function",
                            "function": {
                                "name": "emit_thing",
                                "arguments": '{"value":"recovered"}',
                            },
                        }
                    ],
                },
                finish="tool_calls",
            ),
        )

    data, _ = await _client(handler).structured([{"role": "user", "content": "go"}], SCHEMA)
    assert data == {"value": "recovered"}
    assert calls["n"] == 2


async def test_structured_raises_after_exhausting_retries():
    def handler(request):
        return httpx.Response(200, json=_completion({"role": "assistant", "content": "prose"}))

    with pytest.raises(StructuredOutputError):
        await _client(handler).structured(
            [{"role": "user", "content": "go"}], SCHEMA, max_retries=1
        )


async def test_malformed_tool_arguments_trigger_retry():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        args = "{not json" if calls["n"] == 1 else '{"value":"fixed"}'
        return httpx.Response(
            200,
            json=_completion(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "1",
                            "type": "function",
                            "function": {"name": "emit_thing", "arguments": args},
                        }
                    ],
                },
                finish="tool_calls",
            ),
        )

    data, _ = await _client(handler).structured([{"role": "user", "content": "go"}], SCHEMA)
    assert data == {"value": "fixed"}


async def test_server_error_is_retried_then_raised():
    def handler(request):
        return httpx.Response(500, json={"error": {"message": "upstream boom"}})

    from app.agents.llm import OpenRouterError

    with pytest.raises(OpenRouterError):
        await _client(handler).chat([{"role": "user", "content": "x"}], max_retries=1)


# --- Live-probe findings (2026-08-24), regression-locked below. -------------
# 1. forced tool_choice works            -> covered above
# 2. message.reasoning IS present        -> must be actively dropped
# 3. HTTP 429 is real and frequent       -> must back off, bounded


# The exact 429 body observed from the live endpoint.
RATE_LIMIT_BODY = {
    "error": {
        "message": "Provider returned error",
        "code": 429,
        "metadata": {
            "raw": "stealth/ox-alpha is temporarily rate-limited upstream. Please retry shortly.",
            "provider_name": "Stealth",
            "is_byok": False,
            "limit_source": "upstream_provider_shared_pool",
        },
    }
}


def _tool_call_message_with_reasoning() -> dict:
    """Shape confirmed by live probe: a normal tool call still carries reasoning."""
    return {
        "role": "assistant",
        "content": "",
        "reasoning": "SECRET CHAIN OF THOUGHT",
        "reasoning_details": [{"text": "ALSO SECRET"}],
        "tool_calls": [
            {
                "id": "1",
                "type": "function",
                "function": {"name": "emit_thing", "arguments": '{"value":"ok"}'},
            }
        ],
    }


async def test_raw_response_copy_is_scrubbed_of_reasoning():
    def handler(request):
        return httpx.Response(
            200, json=_completion(_tool_call_message_with_reasoning(), finish="tool_calls")
        )

    r = await _client(handler).chat([{"role": "user", "content": "x"}])
    assert "SECRET" not in repr(r.raw), "raw response must not carry chain of thought"
    assert "reasoning" not in r.raw["choices"][0]["message"]
    assert "reasoning_details" not in r.raw["choices"][0]["message"]
    # Scrubbing must not damage the parts we actually use.
    assert r.tool_calls[0].arguments == {"value": "ok"}


async def test_structured_result_never_contains_reasoning():
    def handler(request):
        return httpx.Response(
            200, json=_completion(_tool_call_message_with_reasoning(), finish="tool_calls")
        )

    data, _ = await _client(handler).structured([{"role": "user", "content": "go"}], SCHEMA)
    assert data == {"value": "ok"}
    assert "SECRET" not in repr(data)


async def test_stream_never_yields_reasoning_deltas():
    lines = (
        'data: {"choices":[{"delta":{"reasoning":"SECRET CHAIN OF THOUGHT"}}]}\n'
        'data: {"choices":[{"delta":{"content":"visible "}}]}\n'
        'data: {"choices":[{"delta":{"reasoning":"MORE SECRET","content":"tail"}}]}\n'
        "data: [DONE]\n"
    )

    def handler(request):
        return httpx.Response(200, text=lines, headers={"content-type": "text/event-stream"})

    chunks = [c async for c in _client(handler).stream([{"role": "user", "content": "x"}])]
    assert chunks == ["visible ", "tail"]
    assert "SECRET" not in "".join(chunks)


async def test_rate_limit_429_is_retried_with_backoff_then_raised(monkeypatch):
    """429 has its own budget: a shared-pool throttle outlasts `max_retries`.

    MEASURED against the live endpoint — three consecutive calls were throttled,
    so the generic 3-attempt budget was not enough to ride it out.
    """
    from app.agents import llm as llm_module

    delays: list[float] = []

    async def fake_sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr(llm_module.asyncio, "sleep", fake_sleep)

    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(429, json=RATE_LIMIT_BODY)

    with pytest.raises(llm_module.RateLimitError):
        await _client(handler).chat([{"role": "user", "content": "x"}], max_retries=3)

    assert calls["n"] == llm_module.MAX_RATE_LIMIT_RETRIES
    assert delays == [2.0, 4.0, 8.0, 16.0], "exponential backoff on a throttle"
    # Bounded: it must terminate, and every wait must respect the cap.
    assert sum(delays) <= 60, "a throttle must never spin without bound"
    assert max(delays) <= llm_module.BACKOFF_CAP_S


async def test_rate_limit_429_recovers_on_retry(monkeypatch):
    from app.agents import llm as llm_module

    async def fake_sleep(seconds):
        return None

    monkeypatch.setattr(llm_module.asyncio, "sleep", fake_sleep)

    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json=RATE_LIMIT_BODY)
        return httpx.Response(200, json=_completion({"role": "assistant", "content": "hi"}))

    r = await _client(handler).chat([{"role": "user", "content": "x"}])
    assert r.content == "hi"
    assert calls["n"] == 2


async def test_body_level_429_under_http_200_is_also_retried(monkeypatch):
    """OpenRouter nests code 429 in the body; it can arrive with a 200 status."""
    from app.agents import llm as llm_module

    async def fake_sleep(seconds):
        return None

    monkeypatch.setattr(llm_module.asyncio, "sleep", fake_sleep)

    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json=RATE_LIMIT_BODY)
        return httpx.Response(200, json=_completion({"role": "assistant", "content": "ok"}))

    r = await _client(handler).chat([{"role": "user", "content": "x"}])
    assert r.content == "ok"
    assert calls["n"] == 2


async def test_permanent_client_error_is_not_retried():
    from app.agents.llm import OpenRouterError, PermanentOpenRouterError

    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(401, json={"error": {"message": "no credits", "code": 401}})

    with pytest.raises(PermanentOpenRouterError):
        await _client(handler).chat([{"role": "user", "content": "x"}], max_retries=3)
    assert calls["n"] == 1, "a bad key will never fix itself; do not burn retries on it"
    assert issubclass(PermanentOpenRouterError, OpenRouterError)


async def test_referer_headers_are_sent():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.headers))
        return httpx.Response(200, json=_completion({"role": "assistant", "content": "x"}))

    await _client(handler).chat([{"role": "user", "content": "x"}])
    assert "http-referer" in seen
    assert "x-title" in seen
