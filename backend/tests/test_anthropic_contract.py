"""Does the installed SDK accept the request this client builds?

This suite exists because it did not. The pin was `anthropic = "^0.75"`, the
client passed `output_config` — the current shape for structured outputs — and
`Messages.create()` rejected it as an unexpected keyword argument. Client-side,
before any network call, so no amount of API credit or key checking would have
revealed it: the first real generation in production would have been a 500, and
the stack trace would have said `TypeError`, which reads like a bug in our code
rather than a stale dependency.

Nothing here calls the API. The mismatch was in a function signature, so a
signature is what is checked: hermetic, instant, and true on a CI box with no
key and no network. The suite that mattered was the one nobody had written.

`temperature` is in the list on purpose even though the client sends it only
when asked: a parameter passed on a rare path is the one that breaks in the
retry nobody exercises.
"""

from __future__ import annotations

import inspect

import anthropic
import pytest

#: Exactly what `AnthropicClient._generate` hands to `messages.create`. Keep in
#: step with it — a keyword added there and not here is untested again.
SENT_BY_THE_CLIENT = [
    "model",
    "max_tokens",
    "system",
    "messages",
    "output_config",
    "temperature",
]


def _accepted() -> set[str]:
    create = anthropic.Anthropic(api_key="not-used").messages.create
    return set(inspect.signature(create).parameters)


@pytest.mark.parametrize("keyword", SENT_BY_THE_CLIENT)
def test_the_installed_sdk_accepts_what_we_send(keyword: str) -> None:
    assert keyword in _accepted(), (
        f"the pinned anthropic SDK ({anthropic.__version__}) rejects {keyword!r}. "
        "Every generation would fail with a TypeError before reaching the API."
    )


def test_structured_output_uses_the_current_parameter() -> None:
    # `output_format` is the deprecated spelling. If a future SDK offers only
    # that one, the client is talking to an API that has moved on.
    accepted = _accepted()
    assert "output_config" in accepted
