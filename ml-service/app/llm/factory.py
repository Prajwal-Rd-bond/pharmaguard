"""
LLM Provider factory.
"""

from __future__ import annotations

from .base import LLMProvider
from .openai_compatible import DisabledLLMProvider, OpenAICompatibleProvider
from ..config import Settings, get_settings


def get_llm_provider(settings: Settings | None = None) -> LLMProvider:
    if settings is None:
        settings = get_settings()

    if not settings.llm_configured:
        return DisabledLLMProvider()

    return OpenAICompatibleProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout_s=settings.llm_timeout_s,
        provider_name=settings.llm_provider,
    )

