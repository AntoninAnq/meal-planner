"""Provider selection.

The only place in the codebase that knows which implementation is in use.
Everything else depends on the `LLMClient` protocol (invariant I8).
"""

from __future__ import annotations

from functools import lru_cache

from app.config import Settings, get_settings
from app.llm.base import LLMClient
from app.llm.fake import FakeLLMClient, valid


def build_llm_client(settings: Settings) -> LLMClient:
    match settings.llm_provider:
        case "ollama":
            from app.llm.ollama import OllamaClient

            return OllamaClient(
                base_url=settings.ollama_base_url,
                model=settings.ollama_model,
                timeout_seconds=settings.ollama_timeout_seconds,
                context_tokens=settings.ollama_context_tokens,
            )
        case "anthropic":
            from app.llm.anthropic_client import AnthropicClient

            if not settings.anthropic_api_key:
                raise RuntimeError("LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is empty")
            return AnthropicClient(
                api_key=settings.anthropic_api_key,
                model=settings.anthropic_model,
            )
        case "fake":
            # Only meaningful as a smoke default; real tests build their own
            # FakeLLMClient with a scripted (often hostile) sequence.
            return FakeLLMClient([valid({})])


@lru_cache(maxsize=1)
def get_llm_client() -> LLMClient:
    return build_llm_client(get_settings())
