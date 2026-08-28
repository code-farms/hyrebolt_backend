import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from pydantic import ValidationError

from app.ai import LLMError, LLMProvider, LLMResponseError, LLMResult
from app.ai.retry import complete_json_with_retries
from app.core.config import Settings
from app.core.logging import get_logger
from app.db.generated.models import Job, JobAnalysis
from app.repositories import JobAnalysisRepository, JobRepository
from app.schemas.analysis import JOB_ANALYSIS_PROMPT_VERSION, JobAnalysisResult

logger = get_logger(__name__)

# Re-exported under the historical name; the value (and the bump rule) live in
# app.schemas.analysis so serializers can hide stale rows.
PROMPT_VERSION = JOB_ANALYSIS_PROMPT_VERSION

SYSTEM_PROMPT = """You extract structured facts from job postings.
Respond with a single JSON object with EXACTLY these keys:
title, seniority, skillsRequired, skillsPreferred, experienceMin, experienceMax,
location, workMode, employmentType, salary, responsibilities, techStack,
industry, confidence.

Rules:
- Use ONLY information stated in the posting. NEVER guess or invent values.
- Any fact the posting does not state is null (or [] for list fields).
- salary is either null or {"min": int|null, "max": int|null, "currency": str|null},
  annual amounts in whole currency units.
- workMode is one of "REMOTE", "HYBRID", "ONSITE" or null.
- employmentType is one of "FULL_TIME", "PART_TIME", "CONTRACT", "INTERNSHIP",
  "FREELANCE", "TEMPORARY", "OTHER" or null.
- experienceMin/experienceMax are years as numbers, or null.
- confidence is your 0..1 confidence that the extraction is faithful.
Return JSON only."""

_MAX_DESCRIPTION_CHARS = 12000


class JobAnalysisService:
    def __init__(
        self,
        provider: LLMProvider,
        analyses: JobAnalysisRepository,
        jobs: JobRepository,
        settings: Settings,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._provider = provider
        self._analyses = analyses
        self._jobs = jobs
        self._settings = settings
        self._sleep = sleep

    async def analyze_job(self, job: Job, *, force: bool = False) -> JobAnalysis:
        """Analyze one job, returning the cached row when a current-version
        analysis already exists."""
        if not force:
            cached = await self._analyses.get_by_job_id(job.id)
            if cached is not None and cached.promptVersion == PROMPT_VERSION:
                return cached

        result = await self._call_provider(self._build_prompt(job))
        validated = self._validate(result.content)
        row = await self._analyses.upsert_for_job(
            job.id,
            analysis=validated.model_dump(mode="json"),
            confidence=validated.confidence,
            model=result.model,
            prompt_version=PROMPT_VERSION,
            input_tokens=result.inputTokens,
            output_tokens=result.outputTokens,
            processed_at=datetime.now(UTC),
        )
        logger.info(
            "job_analyzed",
            job_id=job.id,
            model=result.model,
            confidence=validated.confidence,
        )
        return row

    async def analyze_unanalyzed(self, *, limit: int = 50) -> int:
        """Batch hook for the daily agent (Phase 9): analyze jobs lacking a
        current-version analysis. Per-job failures are logged and skipped."""
        jobs = await self._jobs.find_unanalyzed(PROMPT_VERSION, limit=limit)
        analyzed = 0
        for job in jobs:
            try:
                await self.analyze_job(job)
                analyzed += 1
            except LLMError as exc:
                logger.warning("job_analysis_failed", job_id=job.id, error=exc.message)
        return analyzed

    def _build_prompt(self, job: Job) -> str:
        description = (job.description or "")[:_MAX_DESCRIPTION_CHARS]
        lines = [
            f"Title: {job.title}",
            f"Company: {job.companyName}",
            f"Location: {job.location or 'not stated'}",
            f"Remote flag from source: {job.remote}; hybrid flag: {job.hybrid}",
            "",
            "Job description:",
            description or "(no description provided)",
        ]
        return "\n".join(lines)

    async def _call_provider(self, prompt: str) -> LLMResult:
        return await complete_json_with_retries(
            self._provider,
            system=SYSTEM_PROMPT,
            prompt=prompt,
            timeout_seconds=self._settings.llm_timeout_seconds,
            max_retries=self._settings.llm_max_retries,
            base_delay=self._settings.llm_retry_base_delay_seconds,
            sleep=self._sleep,
            event="job_analysis_retry",
        )

    def _validate(self, content: dict) -> JobAnalysisResult:
        try:
            return JobAnalysisResult.model_validate(content)
        except ValidationError as exc:
            raise LLMResponseError(f"analysis failed validation: {exc}") from exc
