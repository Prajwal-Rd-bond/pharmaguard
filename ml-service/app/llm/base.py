"""
LLM Provider abstraction.

Defines the contract for LLM inference (OpenRouter, local Ollama, etc.)
allowing seamless provider swapping without modifying pipeline code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type, TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def complete(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 2000,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Execute a chat completion and return the raw string response."""
        pass

    @abstractmethod
    async def complete_structured(
        self,
        messages: List[Dict[str, str]],
        schema: Type[T],
        temperature: float = 0.1,
        max_tokens: int = 2000,
    ) -> T:
        """Execute a chat completion and parse the output into a validated Pydantic model."""
        pass

