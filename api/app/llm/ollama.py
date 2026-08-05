"""Ollama implementation — the development workhorse.

Runs on the HOST, not in a container (docs/ARCHITECTURE.md §7.3). Target model
is an 8B q4: the dev machine has no GPU and ~8 GB of free RAM, so a 27B q3
(13 GB) would swap and make the workstation unusable.

Uses Ollama's `format` field for schema-constrained decoding — not "a prompt
that politely asks for JSON".
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
        timeout_seconds: float = 180.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds

    def _generate(
        self,
        *,
        instructions: str,
        context: str,
        schema: dict[str, Any],
        attempt: int,
    ) -> RawCompletion:
        system = instructions if attempt == 1 else instructions + _REPAIR_HINT

        payload = {
            "model": self._model,
            "system": system,
            "prompt": context,
            "format": schema,
            "stream": False,
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
        return RawCompletion(
            text=body.get("response", ""),
            input_tokens=int(body.get("prompt_eval_count", 0)),
            output_tokens=int(body.get("eval_count", 0)),
            model_id=body.get("model", self._model),
        )
