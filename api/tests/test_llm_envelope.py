"""The envelope — hostile LLM output (docs/ARCHITECTURE.md §13.1, layer 2).

This is the harness. Without tests that inject invalid LLM output, the
re-validation code is never executed before the day it matters, and it will be
wrong: the classic failure mode is a validator that exists, has never been seen
rejecting anything, and lets things through.

No real LLM is ever called here. CI stays deterministic, fast and free.
"""

from typing import Any

import pytest

from app.llm.base import LLMError, SchemaValidationError
from app.llm.fake import (
    FakeLLMClient,
    malformed_json,
    not_an_object,
    unavailable,
    valid,
    wrong_shape,
)

# A miniature version of the week-plan envelope: the model emits IDENTIFIERS,
# never prose (§6.5).
PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "dishes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "day_of_week": {"type": "integer", "minimum": 0, "maximum": 6},
                    "recipe_id": {"type": "string"},
                    "member_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["day_of_week", "recipe_id", "member_ids"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["dishes"],
    "additionalProperties": False,
}

GOOD_PAYLOAD = {
    "dishes": [
        {"day_of_week": 0, "recipe_id": "r_012", "member_ids": ["m_1", "m_2"]},
        {"day_of_week": 0, "recipe_id": "r_037", "member_ids": ["m_3"]},
    ]
}


def _call(client: FakeLLMClient, max_attempts: int = 3):
    return client.complete_structured(
        instructions="You arbitrate among pre-filtered candidates.",
        context="candidates: r_012, r_037 | signals: legumes 23d, fish 4d",
        schema=PLAN_SCHEMA,
        max_attempts=max_attempts,
    )


def test_valid_output_passes_on_first_attempt() -> None:
    result = _call(FakeLLMClient([valid(GOOD_PAYLOAD)]))

    assert result.data == GOOD_PAYLOAD
    assert result.attempts == 1
    assert result.model_id == "fake"


def test_malformed_json_is_rejected_then_recovered() -> None:
    client = FakeLLMClient([malformed_json(), valid(GOOD_PAYLOAD)])
    result = _call(client)

    assert result.attempts == 2
    assert result.data == GOOD_PAYLOAD


def test_top_level_array_is_rejected() -> None:
    client = FakeLLMClient([not_an_object(), valid(GOOD_PAYLOAD)])
    assert _call(client).attempts == 2


def test_schema_mismatch_is_rejected() -> None:
    client = FakeLLMClient([wrong_shape(), valid(GOOD_PAYLOAD)])
    assert _call(client).attempts == 2


def test_out_of_range_day_is_rejected() -> None:
    """A plausible-looking plan that violates the schema must not slip through."""
    bad = {"dishes": [{"day_of_week": 9, "recipe_id": "r_012", "member_ids": ["m_1"]}]}
    client = FakeLLMClient([valid(bad), valid(GOOD_PAYLOAD)])
    assert _call(client).attempts == 2


def test_extra_field_is_rejected() -> None:
    """`additionalProperties: false` is what keeps the model inside the envelope."""
    bad = {
        "dishes": [
            {
                "day_of_week": 0,
                "recipe_id": "r_012",
                "member_ids": ["m_1"],
                "commentary": "I picked this because it is lovely",
            }
        ]
    }
    client = FakeLLMClient([valid(bad), valid(GOOD_PAYLOAD)])
    assert _call(client).attempts == 2


def test_attempts_are_bounded_and_the_failure_is_explicit() -> None:
    client = FakeLLMClient([malformed_json()])

    with pytest.raises(SchemaValidationError) as excinfo:
        _call(client, max_attempts=3)

    assert excinfo.value.attempts == 3
    assert len(client.calls) == 3


def test_provider_failure_is_not_swallowed() -> None:
    """A provider that is down must surface, not look like a schema problem."""
    client = FakeLLMClient([unavailable()])

    with pytest.raises(LLMError):
        _call(client)


def test_telemetry_accumulates_across_retries() -> None:
    """The eval harness (§14.5) reads these off the return value, not off logs."""
    client = FakeLLMClient(
        [malformed_json(), valid(GOOD_PAYLOAD)],
        input_tokens=1_500,
        output_tokens=300,
    )
    result = _call(client)

    assert result.input_tokens == 3_000
    assert result.output_tokens == 600
    assert result.latency_ms >= 0


def test_repair_hint_is_only_added_after_a_failure() -> None:
    """Attempt 1 must carry the stable instructions verbatim — it is what gets cached."""
    client = FakeLLMClient([malformed_json(), valid(GOOD_PAYLOAD)])
    _call(client)

    assert client.calls[0]["attempt"] == 1
    assert client.calls[1]["attempt"] == 2


def test_max_attempts_must_be_positive() -> None:
    with pytest.raises(ValueError):
        _call(FakeLLMClient([valid(GOOD_PAYLOAD)]), max_attempts=0)
