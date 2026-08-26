"""Deterministic provider for development and tests. Default in dev so the
app never requires an API key. Extracts nothing it cannot see: the canned
result echoes the prompt's own title marker and leaves everything else null,
honoring the "never invent data" rule.

The response shape is chosen from the casefolded FIRST LINE of the system
prompt (every service's prompt opens with a one-line task statement):
- mentions "application assistant" -> {"content": placeholder draft} (Phase 15)
- mentions "resume" and "gap"      -> resume gap-analysis shape (Phase 14)
- mentions "resume"                -> resume extraction shape (Phase 14)
- otherwise                        -> job-analysis shape (Phase 7)"""

from collections.abc import Callable
from typing import Any

from app.ai.base import LLMProvider, LLMResult

Responder = Callable[[str, str], dict[str, Any]]


def _prompt_line(prompt: str, label: str) -> str | None:
    for line in prompt.splitlines():
        if line.startswith(f"{label}: "):
            return line.removeprefix(f"{label}: ").strip() or None
    return None


def _job_analysis_shape(prompt: str) -> dict[str, Any]:
    # The analysis prompt embeds "Title: <...>" — echo it back, nothing more.
    title = _prompt_line(prompt, "Title")
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


def _resume_shape() -> dict[str, Any]:
    return {
        "summary": None,
        "totalYearsExperience": None,
        "experience": [],
        "skills": [],
        "technologies": [],
        "projects": [],
        "education": [],
        "achievements": [],
        "confidence": 0.1,
    }


def _gap_shape() -> dict[str, Any]:
    return {"relevantExperience": [], "weakAreas": [], "suggestedImprovements": []}


def _assistant_shape(system: str, prompt: str) -> dict[str, Any]:
    """An honest placeholder, never prose that could pass for a real draft."""
    first_line = (system.strip().splitlines() or [""])[0]
    section = first_line.split("—", 1)[1].strip().rstrip(".") if "—" in first_line else "draft"
    title = _prompt_line(prompt, "Title") or "this role"
    company = _prompt_line(prompt, "Company") or "the company"
    return {
        "content": (
            f"[Mock draft] {section} for {title} at {company}.\n\n"
            "The mock LLM provider does not write real content. Set LLM_PROVIDER=openai "
            "(and OPENAI_API_KEY) to generate drafts from your profile and resume."
        )
    }


def _default_responder(system: str, prompt: str) -> dict[str, Any]:
    first_line = (system.strip().splitlines() or [""])[0].casefold()
    if "application assistant" in first_line:
        return _assistant_shape(system, prompt)
    if "resume" in first_line and "gap" in first_line:
        return _gap_shape()
    if "resume" in first_line:
        return _resume_shape()
    return _job_analysis_shape(prompt)


class MockLLMProvider(LLMProvider):
    def __init__(self, responder: Responder | None = None) -> None:
        self._responder = responder or _default_responder
        self.calls = 0

    async def complete_json(self, *, system: str, prompt: str) -> LLMResult:
        self.calls += 1
        content = self._responder(system, prompt)
        return LLMResult(content=content, model="mock", inputTokens=0, outputTokens=0)
