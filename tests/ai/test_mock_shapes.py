"""The mock provider picks its JSON shape from the system prompt's first line,
so every LLM-backed service validates cleanly in dev/tests."""

from app.ai import MockLLMProvider
from app.schemas.analysis import JobAnalysisResult
from app.schemas.resume import GapAIResult, ResumeAnalysisResult
from app.services import job_analysis_service, resume_analysis_service, resume_gap_service


async def test_mock_shapes_follow_the_task_line() -> None:
    provider = MockLLMProvider()

    job = await provider.complete_json(system=job_analysis_service.SYSTEM_PROMPT, prompt="Title: SDE\n")
    assert JobAnalysisResult.model_validate(job.content).title == "SDE"

    resume = await provider.complete_json(system=resume_analysis_service.SYSTEM_PROMPT, prompt="x")
    parsed = ResumeAnalysisResult.model_validate(resume.content)
    assert parsed.skills == [] and parsed.summary is None and parsed.confidence == 0.1

    gap = await provider.complete_json(system=resume_gap_service.SYSTEM_PROMPT, prompt="x")
    assert GapAIResult.model_validate(gap.content).suggestedImprovements == []

    # Only the first line counts: mentioning resumes later never flips the shape.
    other = await provider.complete_json(
        system="You explain matches.\nDo not read the resume gap section.", prompt="Title: X"
    )
    assert "skillsRequired" in other.content


async def test_assistant_shape_wins_over_resume_branch() -> None:
    from app.models import ApplicationDraftKind
    from app.services import application_assistant_service

    provider = MockLLMProvider()
    tailoring = application_assistant_service.SYSTEM_PROMPTS[ApplicationDraftKind.RESUME_TAILORING]
    result = await provider.complete_json(
        system=tailoring, prompt="JOB\nTitle: SDE II\nCompany: Acme\n"
    )
    assert set(result.content) == {"content"}
    assert "Resume tailoring suggestions for SDE II at Acme" in result.content["content"]
    assert "Mock" in result.content["content"]  # never passes for a real draft
