"""Fake implementation — the harness.

This is the THIRD real implementation of the interface, not a test double bolted
on afterwards. It exists so the CI can drive the graph with *hostile* model
output and prove the re-validation layer actually rejects and retries.

Without tests that inject invalid LLM output, the re-validation code is never
executed before the day it matters. It will be wrong. That is the classic
failure mode of this architecture: the validator exists, nobody has ever seen it
reject anything, and it lets things through.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from typing import Any

from app.llm.base import LLMError, RawCompletion, RetryingLLMClient

MODEL_ID = "fake"


class FakeLLMClient(RetryingLLMClient):
    """Replays a scripted sequence of raw completions.

    A string is returned verbatim as model output (so it can be malformed on
    purpose). An exception is raised instead of answering.
    """

    def __init__(
        self,
        responses: Sequence[str | Exception],
        *,
        input_tokens: int = 1_500,
        output_tokens: int = 300,
    ) -> None:
        if not responses:
            raise ValueError("FakeLLMClient needs at least one scripted response")
        self._responses: Iterator[str | Exception] = iter(responses)
        self._last: str | Exception = responses[-1]
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self.calls: list[dict[str, Any]] = []

    def _generate(
        self,
        *,
        instructions: str,
        context: str,
        schema: dict[str, Any],
        attempt: int,
    ) -> RawCompletion:
        self.calls.append(
            {
                "instructions": instructions,
                "context": context,
                "schema": schema,
                "attempt": attempt,
            }
        )

        # Once the script runs out, keep replaying the last entry: a test that
        # cares about attempt counts should assert on them, not be rescued by a
        # StopIteration that looks like a different failure.
        response = next(self._responses, self._last)

        if isinstance(response, Exception):
            raise response

        return RawCompletion(
            text=response,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            model_id=MODEL_ID,
        )


# --- Hostile output builders -------------------------------------------------
#
# The mandatory list. Kept here so every test suite reaches for the
# same ones and none is quietly forgotten.


def valid(payload: dict[str, Any]) -> str:
    return json.dumps(payload)


def malformed_json() -> str:
    return '{"slots": [{"day": "monday",'


def not_an_object() -> str:
    return '["monday", "tuesday"]'


def wrong_shape() -> str:
    """Well-formed JSON object that violates the schema."""
    return '{"unexpected": true}'


def unavailable(message: str = "provider is down") -> LLMError:
    return LLMError(message)
