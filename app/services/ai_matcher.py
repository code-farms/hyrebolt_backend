"""AI explanation layer for matches (Phase 8).

Strictly additive: the deterministic rule scores are computed first and are
never altered here. The AI contributes whyMatch / missingSkills / strengths /
concerns / recommendation — and when it is unavailable or returns garbage,
the match simply ships without it (recommendation falls back to score bands
in the matching service)."""

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.ai import LLMError, LLMProvider
from app.core.logging import get_logger
from app.db.generated.models import Job, UserProfile
from app.models import MatchRecommendation
from app.schemas.analysis import JobAnalysisResult
from app.services.rule_based_matcher import ComponentScores

logger = get_logger(__name__)

MATCH_PROMPT_VERSION = "match-v1"

SYSTEM_PROMPT = """You explain how well a job posting fits a candidate.
Respond with a single JSON object with EXACTLY these keys:
whyMatch (string), missingSkills (string[]), strengths (string[]),
concerns (string[]), recommendation (one of "MUST_APPLY", "STRONG_MATCH",
"CONSIDER", "LOW_PRIORITY", "IGNORE").

Rules:
- Base statements ONLY on the provided profile and job facts. Never invent.
- missingSkills: required skills the candidate does not list.
- Be concise and specific. Return JSON only."""


class AIMatchResult(BaseModel):
    whyMatch: str | None = None
    missingSkills: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    recommendation: MatchRecommendation | None = None

    @field_validator("recommendation", mode="before")
    @classmethod
    def normalize_recommendation(cls, value: object) -> str | None:
        if not isinstance(value, str):
            return None
        upper = value.strip().upper().replace("-", "_").replace(" ", "_")
        return upper if upper in MatchRecommendation.__members__ else None


class AIMatcher:
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def explain(
        self,
        profile: UserProfile,
        job: Job,
        analysis: JobAnalysisResult | None,
        components: ComponentScores,
        overall: float,
    ) -> tuple[AIMatchResult, str] | None:
        """Returns (result, model) or None when the AI layer is unavailable —
        callers must treat None as 'match ships without AI fields'."""
        prompt = self._build_prompt(profile, job, analysis, components, overall)
        try:
            result = await self._provider.complete_json(system=SYSTEM_PROMPT, prompt=prompt)
            validated = AIMatchResult.model_validate(result.content)
        except (LLMError, ValidationError) as exc:
            logger.warning("ai_match_unavailable", job_id=job.id, error=str(exc))
            return None
        return validated, result.model

    def _build_prompt(
        self,
        profile: UserProfile,
        job: Job,
        analysis: JobAnalysisResult | None,
        components: ComponentScores,
        overall: float,
    ) -> str:
        skills = ", ".join(
            f"{us.skill.name} ({us.proficiency})"
            for us in profile.skills or []
            if us.skill
        )
        job_skills = ""
        if analysis is not None:
            job_skills = (
                f"Required skills: {', '.join(analysis.skillsRequired) or 'not stated'}\n"
                f"Preferred skills: {', '.join(analysis.skillsPreferred) or 'not stated'}\n"
            )
        description = (job.description or "")[:4000]
        return (
            "CANDIDATE PROFILE\n"
            f"Current role: {profile.currentRole or 'not stated'}\n"
            f"Years of experience: {profile.yearsOfExperience or 'not stated'}\n"
            f"Target roles: {', '.join(profile.targetRoles) or 'not stated'}\n"
            f"Skills: {skills or 'not stated'}\n"
            f"Preferred locations: {', '.join(profile.preferredLocations) or 'not stated'}\n"
            f"Work mode preference: {profile.remotePreference}\n"
            "\nJOB\n"
            f"Title: {job.title}\n"
            f"Company: {job.companyName}\n"
            f"Location: {job.location or 'not stated'} (remote={job.remote}, hybrid={job.hybrid})\n"
            f"{job_skills}"
            f"Description: {description or 'not provided'}\n"
            "\nDETERMINISTIC SCORES (0-100, already computed — do not change)\n"
            f"Overall: {overall}; role={components.role}, skills={components.skill}, "
            f"experience={components.experience}, location={components.location}, "
            f"salary={components.salary}, workMode={components.workMode}, "
            f"industry={components.industry}, company={components.company}"
        )
