from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class LLMResult:
    content: dict[str, Any]  # parsed JSON object
    model: str
    inputTokens: int | None = None
    outputTokens: int | None = None


class LLMProvider(ABC):
    """The only surface business logic may depend on. Implementations must
    return structured JSON (a parsed dict), never free text."""

    @abstractmethod
    async def complete_json(self, *, system: str, prompt: str) -> LLMResult: ...
