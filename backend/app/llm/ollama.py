"""Ollama implementation — the development workhorse.

Runs on the HOST, not in a container. Target model is an 8B q4: the dev machine
has no GPU, so a 27B q3 (13 GB) would swap and make the workstation unusable.
Weights are ~4.9 GiB, and the KV cache reserved for the context window comes on
top of that — see `ollama_context_tokens`.

Uses Ollama's `format` field for schema-constrained decoding — not "a prompt
that politely asks for JSON".

**The context window is declared, and overflowing it is an error.** Ollama's
default is 4 096 tokens where `qwen3:8b` declares 40 960, so leaving it unset
spent a tenth of the model by accident. Worse, past that limit Ollama does not
refuse — it TRUNCATES, silently, keeping the tail. `build_context` puts the
candidate list last and the eaters first, so the block that goes is the one
naming who has to be fed. The plan would then be composed for nobody, the
envelope check would reject it, and the whole thing would read as "the 8B
cannot do this". Measured, not imagined: at 279 candidates the prompt was cut
from 8 709 tokens to exactly 4 096, and the only trace was `prompt_eval_count`
landing on a round number.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.llm.base import LLMUnavailableError, RawCompletion, RetryingLLMClient

_REPAIR_HINT = (
    "\n\nYour previous answer did not match the required schema. "
    "Return ONLY a JSON object matching it exactly, with no commentary."
)


class OllamaClient(RetryingLLMClient):
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float,
        context_tokens: int,
        keep_alive: str = "30m",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds
        self._context_tokens = context_tokens
        self._keep_alive = keep_alive

    def _generate(
        self,
        *,
        instructions: str,
        context: str,
        schema: dict[str, Any],
        attempt: int,
        temperature: float | None = None,
    ) -> RawCompletion:
        system = instructions if attempt == 1 else instructions + _REPAIR_HINT

        options: dict[str, Any] = {"num_ctx": self._context_tokens}
        if temperature is not None:
            options["temperature"] = temperature

        payload: dict[str, Any] = {
            "model": self._model,
            "system": system,
            "prompt": context,
            "format": schema,
            "stream": False,
            "options": options,
            # Ollama unloads a model after five idle minutes by default, and
            # the next request pays for reading ~5 GiB back from disk. Between
            # two things a household does in one sitting — read the week,
            # regenerate a slot — five minutes is nothing, and the second
            # action would look inexplicably slower than the first.
            #
            # It is a RESERVATION of memory, not of compute: the weights sit in
            # RAM doing nothing. Same trade as `num_ctx` — memory is cheap here
            # and latency is what the household feels.
            "keep_alive": self._keep_alive,
        }

        try:
            response = httpx.post(
                f"{self._base_url}/api/generate",
                json=payload,
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMUnavailableError(f"ollama unreachable at {self._base_url}: {exc}") from exc

        body = response.json()
        input_tokens = int(body.get("prompt_eval_count", 0))

        # Ollama reports truncation nowhere else: the count simply stops at the
        # window. Refusing here is deliberate — a plan built on an amputated
        # prompt is worse than no plan, because nothing downstream can tell the
        # difference. Treated as unavailability rather than as a bad answer:
        # retrying the same prompt would truncate identically, so the retry
        # loop must not swallow it as a shape failure.
        if input_tokens >= self._context_tokens:
            raise LLMUnavailableError(
                f"prompt truncated: {input_tokens} tokens reached the "
                f"{self._context_tokens}-token window. Raise OLLAMA_CONTEXT_TOKENS "
                f"or send fewer candidates — the block that gets cut is the eaters."
            )

        return RawCompletion(
            text=body.get("response", ""),
            input_tokens=input_tokens,
            output_tokens=int(body.get("eval_count", 0)),
            model_id=body.get("model", self._model),
        )
