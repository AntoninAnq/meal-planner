"""The context window, and the failure it used to hide.

Ollama's default is 4 096 tokens where `qwen3:8b` declares 40 960. Past the
window Ollama does not refuse — it truncates, keeps the tail, and reports it
nowhere except in `prompt_eval_count` landing exactly on the limit.

`build_context` puts `CANDIDATES` last and `EATERS` first, so what survives is
the list of allowed dishes and what disappears is the list of people to feed.
Measured on the real catalogue: at 279 candidates an 8 709-token prompt came
back counted as 4 096.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.llm.base import LLMUnavailableError
from app.llm.ollama import OllamaClient

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}}


def _client(monkeypatch, *, prompt_eval_count: int, context_tokens: int = 8192) -> OllamaClient:
    """An Ollama that answers well-formed JSON and reports a given token count."""
    captured: dict = {}

    def fake_post(url: str, *, json: dict, timeout: float) -> httpx.Response:  # noqa: A002
        captured.update(json)
        return httpx.Response(
            200,
            json={
                "response": '{"ok": true}',
                "prompt_eval_count": prompt_eval_count,
                "eval_count": 12,
                "model": "qwen3:8b",
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    client = OllamaClient(
        base_url="http://ollama.invalid",
        model="qwen3:8b",
        timeout_seconds=1.0,
        context_tokens=context_tokens,
    )
    client.captured = captured  # type: ignore[attr-defined]
    return client


def test_the_window_is_declared_on_every_request(monkeypatch) -> None:
    """Left unset, Ollama picks 4 096 and the model's other 36 864 go unused.

    A technical value nobody wrote down is exactly what I8 forbids — and this
    one silently caps how many candidates the pre-filter may send.
    """
    client = _client(monkeypatch, prompt_eval_count=900)
    client.complete_structured(instructions="x", context="y", schema=SCHEMA)

    assert client.captured["options"]["num_ctx"] == 8192  # type: ignore[attr-defined]


def test_a_temperature_does_not_evict_the_window(monkeypatch) -> None:
    """Both live in `options`, and the retry path sets a temperature.

    Written as a test because the natural way to add a temperature is to assign
    `options` wholesale, which drops `num_ctx` on precisely the attempts that
    follow a rejection.
    """
    client = _client(monkeypatch, prompt_eval_count=900)
    client.complete_structured(instructions="x", context="y", schema=SCHEMA, temperature=0.7)

    options = client.captured["options"]  # type: ignore[attr-defined]
    assert options["num_ctx"] == 8192
    assert options["temperature"] == 0.7


def test_a_truncated_prompt_is_refused_rather_than_answered(monkeypatch) -> None:
    """The answer looks perfectly valid. That is the whole problem.

    A plan composed without the eaters passes every shape check, fails the
    envelope, and reads as "the model cannot do this". Refusing turns a silent
    wrong answer into a loud, actionable one.
    """
    client = _client(monkeypatch, prompt_eval_count=8192)

    with pytest.raises(LLMUnavailableError, match="truncated"):
        client.complete_structured(instructions="x", context="y", schema=SCHEMA)


def test_a_prompt_that_merely_fits_is_not_refused(monkeypatch) -> None:
    """One token below the window is a normal, complete prompt."""
    client = _client(monkeypatch, prompt_eval_count=8191)

    result = client.complete_structured(instructions="x", context="y", schema=SCHEMA)
    assert result.input_tokens == 8191


def test_truncation_is_not_retried_as_a_shape_failure(monkeypatch) -> None:
    """Replaying an identical prompt truncates identically.

    `LLMUnavailableError` is what the retry loop lets through; a shape error
    would be re-sent up to `llm_max_attempts` times, paying the full latency
    three times over to obtain the same amputated prompt.
    """
    calls = {"n": 0}

    def counting_post(url: str, *, json: dict, timeout: float) -> httpx.Response:  # noqa: A002
        calls["n"] += 1
        return httpx.Response(
            200,
            json={"response": '{"ok": true}', "prompt_eval_count": 4096, "eval_count": 1},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", counting_post)
    client = OllamaClient(
        base_url="http://ollama.invalid",
        model="qwen3:8b",
        timeout_seconds=1.0,
        context_tokens=4096,
    )

    with pytest.raises(LLMUnavailableError):
        client.complete_structured(instructions="x", context="y", schema=SCHEMA)
    assert calls["n"] == 1


def test_the_error_names_the_block_that_disappears(monkeypatch) -> None:
    """Ollama keeps the TAIL, and the eaters are at the head of the context.

    Someone reading this error at 23:00 needs to know that widening the window
    or sending fewer candidates is the fix — not that the model is unreachable.
    """
    client = _client(monkeypatch, prompt_eval_count=8192)

    with pytest.raises(LLMUnavailableError) as raised:
        client.complete_structured(instructions="x", context="y", schema=SCHEMA)

    message = str(raised.value)
    assert "OLLAMA_CONTEXT_TOKENS" in message
    assert "eaters" in message


def test_json_stays_the_transport_shape(monkeypatch) -> None:
    """Guards the fake above: the client must still send a schema to constrain."""
    client = _client(monkeypatch, prompt_eval_count=10)
    client.complete_structured(instructions="i", context="c", schema=SCHEMA)

    assert client.captured["format"] == SCHEMA  # type: ignore[attr-defined]
    assert client.captured["system"] == "i"  # type: ignore[attr-defined]
    assert json.dumps(client.captured["options"])  # type: ignore[attr-defined]
