"""LLM provider abstraction (Phase 7). Business logic depends only on
LLMProvider; concrete providers are swappable via configuration."""

from app.ai.base import LLMProvider, LLMResult
from app.ai.exceptions import LLMError, LLMRateLimitedError, LLMResponseError
from app.ai.mock_provider import MockLLMProvider
from app.ai.openai_provider import OpenAIProvider

__all__ = [
    "LLMError",
    "LLMProvider",
    "LLMRateLimitedError",
    "LLMResponseError",
    "LLMResult",
    "MockLLMProvider",
    "OpenAIProvider",
]
