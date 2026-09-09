"""Reading what Anthropic sends back — the half a valid key would have proven.

The request half is covered by `test_anthropic_contract`: a signature check
that caught the SDK pin rejecting `output_config`. This file covers the other
half, which that check cannot reach — what happens to the object that comes
back. Both halves had never been executed once: the eval bench has only ever
run on `qwen3:8b`, so no line of `anthropic_client` had run anywhere, in any
environment, before the day someone deployed it.

The response is stubbed rather than fetched. That is not a compromise forced by
the missing key: response SHAPE is what this code gets wrong — a renamed field,
a block type it does not expect, a refusal it forgets to check — and a stub
pins every one of those without spending a cent or needing a network. What a
real call adds on top is whether the service accepts our JSON schema, and that
is one test, run once, when the key exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import anthropic
import httpx
import pytest

from app.llm.anthropic_client import AnthropicClient
from app.llm.base import LLMUnavailableError

SCHEMA: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}


@dataclass
class Block:
    type: str
    text: str = ""


@dataclass
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass
class Response:
    content: list[Block]
    usage: Usage
    model: str
    stop_reason: str = "end_turn"


def client_returning(response: object) -> AnthropicClient:
    client = AnthropicClient(api_key="not-used", model="claude-haiku-4-5")

    def create(**_: object) -> object:
        return response

    client._client.messages.create = create  # type: ignore[method-assign]
    return client


def client_raising(error: Exception) -> AnthropicClient:
    client = AnthropicClient(api_key="not-used", model="claude-haiku-4-5")

    def create(**_: object) -> object:
        raise error

    client._client.messages.create = create  # type: ignore[method-assign]
    return client


def generate(client: AnthropicClient) -> Any:
    return client._generate(instructions="i", context="c", schema=SCHEMA, attempt=1)


def test_the_text_block_becomes_the_completion() -> None:
    result = generate(
        client_returning(
            Response(
                content=[Block("text", '{"slots": []}')],
                usage=Usage(1500, 300),
                model="claude-haiku-4-5",
            )
        )
    )

    assert result.text == '{"slots": []}'
    # Tokens are what `generation_log` bills on, and what tells a 0.7-centime
    # week from a runaway one.
    assert (result.input_tokens, result.output_tokens) == (1500, 300)
    # The model the service actually used, not the one we asked for.
    assert result.model_id == "claude-haiku-4-5"


def test_a_thinking_block_before_the_text_is_skipped() -> None:
    # The response is a LIST of blocks and the answer is not always first.
    # Taking `content[0]` would return an empty string here, and the caller
    # would report malformed JSON from a perfectly good answer.
    result = generate(
        client_returning(
            Response(
                content=[Block("thinking"), Block("text", '{"ok": true}')],
                usage=Usage(10, 5),
                model="m",
            )
        )
    )

    assert result.text == '{"ok": true}'


def test_a_response_with_no_text_block_yields_an_empty_completion() -> None:
    # Empty rather than an IndexError: the retry loop above knows what to do
    # with an unparseable answer, and nothing sensible with a crash.
    result = generate(
        client_returning(Response(content=[], usage=Usage(10, 0), model="m"))
    )

    assert result.text == ""


def test_a_refusal_is_not_treated_as_an_answer() -> None:
    # HTTP 200 with `stop_reason: refusal`. Read as content it would be an
    # empty string, retried three times, and billed three times.
    with pytest.raises(LLMUnavailableError, match="declined"):
        generate(
            client_returning(
                Response(
                    content=[],
                    usage=Usage(10, 0),
                    model="m",
                    stop_reason="refusal",
                )
            )
        )


def _http_error(status: int) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("POST", "https://api.anthropic.com"))


def test_rate_limiting_is_reported_as_unavailable() -> None:
    error = anthropic.RateLimitError("slow down", response=_http_error(429), body=None)

    with pytest.raises(LLMUnavailableError, match="rate limited"):
        generate(client_raising(error))


def test_a_server_error_carries_its_status_into_the_message() -> None:
    # The status is what tells a quota problem from an outage when the only
    # thing left is a log line.
    error = anthropic.APIStatusError("boom", response=_http_error(529), body=None)

    with pytest.raises(LLMUnavailableError, match="529"):
        generate(client_raising(error))


def test_an_unreachable_service_is_reported_as_unavailable() -> None:
    error = anthropic.APIConnectionError(
        request=httpx.Request("POST", "https://api.anthropic.com")
    )

    with pytest.raises(LLMUnavailableError, match="unreachable"):
        generate(client_raising(error))
