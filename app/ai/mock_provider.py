"""Deterministic provider for development and tests. Default in dev so the
app never requires an API key. Extracts nothing it cannot see: the canned
result echoes the prompt's own title marker and leaves everything else null,
honoring the "never invent data" rule."""

from collections.abc import Callable
from typing import Any

from app.ai.base import LLMProvider, LLMResult

Responder = Callable[[str, str], dict[str, Any]]


def _default_responder(system: str, prompt: str) -> dict[str, Any]:
    # The analysis prompt embeds "Title: <...>" — echo it back, nothing more.
    title = None
    for line in prompt.splitlines():
        if line.startswith("Title: "):
            title = line.removeprefix("Title: ").strip() or None
            break
    return {
        "title": title,
        "seniority": None,
        "skillsRequired": [],
        "skillsPreferred": [],
        "experienceMin": None,
        "experienceMax": None,
        "location": None,
        "workMode": None,
        "employmentType": None,
        "salary": None,
        "responsibilities": [],
        "techStack": [],
        "industry": None,
        "confidence": 0.1,
    }


class MockLLMProvider(LLMProvider):
    def __init__(self, responder: Responder | None = None) -> None:
        self._responder = responder or _default_responder
        self.calls = 0

    async def complete_json(self, *, system: str, prompt: str) -> LLMResult:
        self.calls += 1
        content = self._responder(system, prompt)
        return LLMResult(content=content, model="mock", inputTokens=0, outputTokens=0)
