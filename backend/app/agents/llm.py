"""OpenRouter gateway.

VERIFIED PLATFORM CONSTRAINT (probed 2026-08-24 against stealth/ox-alpha):
`response_format={"type":"json_schema", ..., "strict": True}` is accepted with
HTTP 200 and then SILENTLY IGNORED — the model replies with markdown prose and
any json.loads() on it raises. Structured output is therefore obtained ONLY by
declaring a function tool and forcing it with tool_choice. Do not "simplify"
this back to response_format.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class OpenRouterError(Exception):
    """Transport, auth, or upstream provider failure."""


class RateLimitError(OpenRouterError):
    """Upstream provider rate-limited us.

    VERIFIED (live probe 2026-08-24): `stealth/ox-alpha` returns HTTP 429 with
    `error.code == 429` and
    `metadata.limit_source == "upstream_provider_shared_pool"` on roughly one
    call in three. It is transient and shared-pool, so the correct response is a
    bounded exponential backoff — NOT surfacing the failure to the user, and NOT
    an unbounded spin. Kept as its own type so the logs distinguish "the
    provider throttled us" from "the model replied in prose", which is the other
    retry loop in this module and has a completely different remedy.
    """


class PermanentOpenRouterError(OpenRouterError):
    """A request the server will reject identically no matter how often we send
    it (bad key, malformed body, unknown model). Retrying only wastes the demo's
    time, so this escapes the retry loop immediately."""


class StructuredOutputError(OpenRouterError):
    """The model would not produce a parseable forced tool call."""


# Transient upstream conditions worth a backoff. Everything else in 4xx is a
# defect in our own request and is raised straight away.
RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

# 429s come from a shared upstream pool, so back off harder than for a 5xx and
# give them their own attempt budget. 5 throttles => 2+4+8+16 = 30s of waiting,
# then a hard failure. Bounded on purpose: the key has a $1 ceiling and a demo
# that silently spins is worse than one that reports a throttle.
RATE_LIMIT_BACKOFF_BASE_S = 2.0
MAX_RATE_LIMIT_RETRIES = 5
BACKOFF_CAP_S = 30.0

# Keys that carry the model's private chain of thought. The brief forbids
# surfacing these, and a live probe confirmed `message.reasoning` IS present on
# ordinary tool-call responses from this model — so it must be actively dropped,
# not merely "never encountered".
_REASONING_KEYS = frozenset({"reasoning", "reasoning_details", "reasoning_content"})


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.prompt_tokens + other.prompt_tokens,
            self.completion_tokens + other.completion_tokens,
            self.total_tokens + other.total_tokens,
            self.cost + other.cost,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost": self.cost,
        }


@dataclass
class ToolCallRequest:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    content: str = ""
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    finish_reason: str = "stop"
    raw: dict[str, Any] = field(default_factory=dict)
    # NOTE: deliberately no `reasoning` attribute. The brief forbids surfacing
    # private model reasoning, so it is discarded here at the boundary rather
    # than carried around and filtered at every call site. `raw` is scrubbed by
    # `_scrub_reasoning` before it is stored, so even the debug copy of the
    # response body cannot leak a chain of thought into an event or a DB row.


def _scrub_reasoning(payload: dict[str, Any]) -> dict[str, Any]:
    """Copy the response body with every private-reasoning key removed.

    `LLMResponse.raw` exists for debugging, and the temptation is to persist it
    or ship it down the SSE channel. Scrubbing here makes that harmless: there
    is no path from an OpenRouter response to the frontend that still carries
    reasoning text.
    """
    scrubbed = {k: v for k, v in payload.items() if k not in _REASONING_KEYS}
    choices = []
    for choice in payload.get("choices") or []:
        if not isinstance(choice, dict):
            choices.append(choice)
            continue
        clean = dict(choice)
        for slot in ("message", "delta"):
            part = clean.get(slot)
            if isinstance(part, dict):
                clean[slot] = {k: v for k, v in part.items() if k not in _REASONING_KEYS}
        choices.append(clean)
    if choices:
        scrubbed["choices"] = choices
    return scrubbed


class OpenRouterClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.openrouter_api_key
        self.model = model or settings.openrouter_model
        self.base_url = base_url or settings.openrouter_base_url
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            # OpenRouter attribution headers.
            "HTTP-Referer": settings.openrouter_app_url,
            "X-Title": settings.openrouter_app_title,
        }

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._headers(),
            timeout=timeout,
            transport=self._transport,
        )

    @staticmethod
    def _parse(payload: dict[str, Any]) -> LLMResponse:
        choice = (payload.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        calls: list[ToolCallRequest] = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function") or {}
            raw_args = fn.get("arguments") or "{}"
            try:
                parsed = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except json.JSONDecodeError:
                parsed = {"__unparsed__": raw_args}
            calls.append(
                ToolCallRequest(id=tc.get("id", ""), name=fn.get("name", ""), arguments=parsed)
            )
        u = payload.get("usage") or {}
        return LLMResponse(
            content=message.get("content") or "",
            tool_calls=calls,
            usage=Usage(
                prompt_tokens=u.get("prompt_tokens", 0),
                completion_tokens=u.get("completion_tokens", 0),
                total_tokens=u.get("total_tokens", 0),
                cost=float(u.get("cost", 0) or 0),
            ),
            finish_reason=choice.get("finish_reason", "stop"),
            raw=_scrub_reasoning(payload),
        )

    @staticmethod
    def _raise_for_payload(status_code: int, body_text: str, error: Any = None) -> None:
        """Turn an OpenRouter failure into the right exception class.

        The provider reports 429 twice: as the HTTP status *and* as
        `error.code` inside the JSON body (which sometimes arrives under an
        HTTP 200). Both are checked so a throttle is never mistaken for a
        permanent error.
        """
        code = status_code
        detail = body_text
        if isinstance(error, dict):
            code = error.get("code") or code
            detail = str(error)[:500]
        if code == 429:
            raise RateLimitError(f"OpenRouter rate limited (429): {detail[:500]}")
        if isinstance(code, int) and 400 <= code < 500 and code not in RETRYABLE_STATUS:
            raise PermanentOpenRouterError(f"OpenRouter HTTP {code}: {detail[:500]}")
        raise OpenRouterError(f"OpenRouter HTTP {code}: {detail[:500]}")

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
        temperature: float | None = None,
        max_tokens: int = 16000,
        timeout: float = 900.0,
        max_retries: int = 3,
    ) -> LLMResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": settings.agent_temperature if temperature is None else temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            body["tools"] = tools
        if tool_choice is not None:
            body["tool_choice"] = tool_choice

        # 429s get their own budget rather than sharing `max_retries`.
        # MEASURED 2026-08-24: the shared upstream pool throttled three
        # consecutive calls, so 3 attempts across ~6s of backoff was not enough
        # to ride it out and the caller saw a hard failure. A throttle is not a
        # defect in our request, so spending more attempts on it is right —
        # bounded at MAX_RATE_LIMIT_RETRIES (~30s worst case) so it can never
        # spin.
        last: Exception | None = None
        attempt = 0
        throttles = 0
        while True:
            try:
                async with self._client(timeout) as client:
                    resp = await client.post("/chat/completions", json=body)
                if resp.status_code >= 400:
                    error = None
                    try:
                        error = (resp.json() or {}).get("error")
                    except ValueError:
                        error = None
                    self._raise_for_payload(resp.status_code, resp.text, error)
                payload = resp.json()
                if payload.get("error"):
                    # A 200 can still carry an upstream error object, 429 included.
                    self._raise_for_payload(200, str(payload["error"]), payload["error"])
                return self._parse(payload)
            except PermanentOpenRouterError:
                # Retrying a bad key or a malformed body just burns wall-clock.
                raise
            except RateLimitError as exc:
                last = exc
                throttles += 1
                if throttles >= MAX_RATE_LIMIT_RETRIES:
                    raise RateLimitError(
                        f"upstream rate limit persisted across {throttles} attempts: {exc}"
                    ) from exc
                delay = min(RATE_LIMIT_BACKOFF_BASE_S * (2 ** (throttles - 1)), BACKOFF_CAP_S)
                # Distinct from both the generic transport retry below and the
                # structured-output retry in `structured()`, so a failed
                # extraction can be diagnosed from the log alone.
                logger.warning(
                    "openrouter TRANSPORT retry: upstream rate limit (429), "
                    "throttle %d/%d; backing off %.1fs — %s",
                    throttles, MAX_RATE_LIMIT_RETRIES, delay, exc,
                )
                await asyncio.sleep(delay)
            except (httpx.TransportError, OpenRouterError) as exc:
                last = exc
                attempt += 1
                if attempt >= max_retries:
                    break
                delay = min(2.0 ** (attempt - 1), BACKOFF_CAP_S)
                logger.warning(
                    "openrouter TRANSPORT retry: attempt %d/%d failed; "
                    "retrying in %.1fs — %s",
                    attempt, max_retries, delay, exc,
                )
                await asyncio.sleep(delay)
        raise OpenRouterError(f"exhausted {max_retries} attempts: {last}")

    async def structured(
        self,
        messages: list[dict[str, Any]],
        tool_schema: dict[str, Any],
        temperature: float = 0.0,
        max_tokens: int = 32000,
        max_retries: int = 2,
    ) -> tuple[dict[str, Any], Usage]:
        """Force the model to emit structured data as a tool call.

        Retries on the two observed failure modes: replying in prose (no tool
        call at all) and emitting malformed JSON in `arguments`.
        """
        name = tool_schema["name"]
        tools = [{"type": "function", "function": tool_schema}]
        forced = {"type": "function", "function": {"name": name}}
        convo = list(messages)
        total = Usage()

        for attempt in range(max_retries + 1):
            response = await self.chat(
                convo,
                tools=tools,
                tool_choice=forced,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            total = total + response.usage

            call = next((c for c in response.tool_calls if c.name == name), None)
            if call is not None and "__unparsed__" not in call.arguments:
                return call.arguments, total

            if attempt == max_retries:
                break

            problem = (
                "your arguments were not valid JSON"
                if call is not None
                else "you replied with prose instead of calling the tool"
            )
            # Distinct wording from the transport retry above: this is a MODEL
            # FORMAT failure (the request itself succeeded), and the remedy is a
            # corrective turn in the conversation, not a backoff.
            logger.warning(
                "openrouter STRUCTURED-OUTPUT retry %d/%d: %s",
                attempt + 1, max_retries, problem,
            )
            convo = convo + [
                {"role": "assistant", "content": response.content[:2000]},
                {
                    "role": "user",
                    "content": (
                        f"That response was unusable: {problem}. "
                        f"You MUST respond by calling the `{name}` function with a single "
                        f"valid JSON object matching its schema. Emit no prose, no markdown, "
                        f"no code fences — only the function call."
                    ),
                },
            ]

        raise StructuredOutputError(
            f"model did not produce a valid `{name}` call after {max_retries + 1} attempts"
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        temperature: float | None = None,
        max_tokens: int = 8000,
        timeout: float = 900.0,
    ) -> AsyncIterator[str]:
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": settings.agent_temperature if temperature is None else temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        async with self._client(timeout) as client:
            async with client.stream("POST", "/chat/completions", json=body) as resp:
                if resp.status_code >= 400:
                    text = await resp.aread()
                    self._raise_for_payload(resp.status_code, repr(text[:500]))
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        delta = json.loads(data)["choices"][0]["delta"]
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    # `delta.reasoning` is intentionally ignored, never yielded.
                    chunk = delta.get("content")
                    if chunk:
                        yield chunk


llm = OpenRouterClient()
