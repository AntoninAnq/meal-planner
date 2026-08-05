"""Anthropic implementation — production.

Claude Haiku 4.5 is the workhorse: ~0.3 cents per week plan (1 500 in / 300 out)
and it supports structured outputs. Sonnet 5 is the quality fallback.

Two model-specific notes that must not be "helpfully" added back:
  * Haiku 4.5 REJECTS the `effort` parameter.
  * Nothing is streamed — the LLM emits identifiers (§6.5).

Invariant I5 is enforced upstream, in the prompt builder: this client never sees
a `member` entity, only the constraint DTO it is handed.
"""

from __future__ import annotations

from typing import Any

import anthropic

from app.llm.base import LLMUnavailableError, RawCompletion, RetryingLLMClient

_REPAIR_HINT = (
    "\n\nYour previous answer did not match the required schema. "
    "Return ONLY a JSON object matching it exactly, with no commentary."
)

# Output is a few hundred tokens of identifiers. The ceiling only needs to be
# comfortably above that.
_MAX_TOKENS = 4096


class AnthropicClient(RetryingLLMClient):
    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def _generate(
        self,
        *,
        instructions: str,
        context: str,
        schema: dict[str, Any],
        attempt: int,
    ) -> RawCompletion:
        system = instructions if attempt == 1 else instructions + _REPAIR_HINT

        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=_MAX_TOKENS,
                # `instructions` is stable and cacheable; `context` changes every
                # call. Keeping them apart is what makes prompt caching possible
                # at all (§7.1).
                system=system,
                messages=[{"role": "user", "content": context}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.RateLimitError as exc:
            raise LLMUnavailableError(f"anthropic rate limited: {exc}") from exc
        except anthropic.APIStatusError as exc:
            raise LLMUnavailableError(f"anthropic returned {exc.status_code}: {exc}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailableError(f"anthropic unreachable: {exc}") from exc

        if response.stop_reason == "refusal":
            raise LLMUnavailableError("anthropic declined the request")

        text = next((b.text for b in response.content if b.type == "text"), "")
        return RawCompletion(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model_id=response.model,
        )
