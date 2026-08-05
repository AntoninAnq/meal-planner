"""The single LLM interface (docs/ARCHITECTURE.md §7.1).

Three real implementations back this protocol — Ollama (dev), Anthropic (prod),
Fake (tests). An interface with three real implementations does not leak; with
one it stays theoretical until the day you swap and discover everything that
escaped through it.

Deliberately absent: `temperature` (removed on recent models, and determinism is
not steered there), `effort` (rejected by Haiku 4.5), `stream` (the LLM emits
identifiers, there is nothing to stream — see §6.5).
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import jsonschema


class LLMError(Exception):
    """Base class for every failure of the LLM layer."""


class LLMUnavailableError(LLMError):
    """The provider could not be reached or refused the request."""


class SchemaValidationError(LLMError):
    """The model never produced output matching the schema, attempts exhausted."""

    def __init__(self, attempts: int, last_error: str) -> None:
        super().__init__(f"no schema-valid output after {attempts} attempt(s): {last_error}")
        self.attempts = attempts
        self.last_error = last_error


@dataclass(frozen=True)
class StructuredResult:
    """A validated structure, plus the telemetry the eval harness aggregates.

    Telemetry lives in the return value on purpose: outside of it, the eval
    script (§14.5) would have to parse logs.
    """

    data: dict[str, Any]
    attempts: int
    input_tokens: int
    output_tokens: int
    model_id: str
    latency_ms: int


@runtime_checkable
class LLMClient(Protocol):
    def complete_structured(
        self,
        *,
        instructions: str,
        context: str,
        schema: dict[str, Any],
        max_attempts: int = 3,
    ) -> StructuredResult: ...


@dataclass(frozen=True)
class RawCompletion:
    """What a provider returns before validation."""

    text: str
    input_tokens: int
    output_tokens: int
    model_id: str


class RetryingLLMClient(ABC):
    """Shared retry + validation loop.

    Retry lives here, not in the graph nodes. Otherwise every node reimplements
    its own loop, differently, and the attempt count becomes unusable for the
    eval harness.
    """

    @abstractmethod
    def _generate(
        self,
        *,
        instructions: str,
        context: str,
        schema: dict[str, Any],
        attempt: int,
    ) -> RawCompletion:
        """One provider call. Attempt index is 1-based, for repair prompting."""

    def complete_structured(
        self,
        *,
        instructions: str,
        context: str,
        schema: dict[str, Any],
        max_attempts: int = 3,
    ) -> StructuredResult:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")

        started = time.monotonic()
        input_tokens = 0
        output_tokens = 0
        model_id = ""
        last_error = "no attempt was made"

        for attempt in range(1, max_attempts + 1):
            completion = self._generate(
                instructions=instructions,
                context=context,
                schema=schema,
                attempt=attempt,
            )
            input_tokens += completion.input_tokens
            output_tokens += completion.output_tokens
            model_id = completion.model_id

            try:
                data = json.loads(completion.text)
            except json.JSONDecodeError as exc:
                last_error = f"malformed JSON: {exc}"
                continue

            if not isinstance(data, dict):
                last_error = f"top level is {type(data).__name__}, expected object"
                continue

            try:
                jsonschema.validate(instance=data, schema=schema)
            except jsonschema.ValidationError as exc:
                last_error = f"schema mismatch at {list(exc.absolute_path)}: {exc.message}"
                continue

            return StructuredResult(
                data=data,
                attempts=attempt,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                model_id=model_id,
                latency_ms=int((time.monotonic() - started) * 1000),
            )

        raise SchemaValidationError(attempts=max_attempts, last_error=last_error)
