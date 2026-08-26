# camelCase wire contract, mirrored by the frontend zod schemas (Phase 11).
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.db.generated.models import JobMatch
from app.models import MatchFeedback, MatchRecommendation, PreferenceSignalKind
from app.schemas.job import JobOut, RankingOut, job_out


class ComponentScoresOut(BaseModel):
    role: float | None
    skill: float | None
    experience: float | None
    location: float | None
    salary: float | None
    workMode: float | None
    industry: float | None
    company: float | None
    # Phase 13: null when the company is not on the viewer's watchlist.
    watchlist: float | None = None


class MatchOut(BaseModel):
    jobId: str
    overallScore: float
    componentScores: ComponentScoresOut
    recommendation: MatchRecommendation | None
    whyMatch: str | None
    missingSkills: list[str]
    strengths: list[str]
    concerns: list[str]
    feedback: MatchFeedback | None
    scoringVersion: str | None
    aiModel: str | None
    promptVersion: str | None
    createdAt: datetime
    updatedAt: datetime


def base_only_ranking(match: JobMatch) -> RankingOut:
    return RankingOut(
        finalScore=match.overallScore,
        baseScore=match.overallScore,
        preferenceScore=0.0,
        freshnessScore=0.0,
        companyScore=0.0,
        feedbackScore=0.0,
        explanations=[],
    )


@dataclass
class RankedMatch:
    match: JobMatch
    ranking: RankingOut


class RecommendedJobOut(BaseModel):
    job: JobOut
    match: MatchOut
    ranking: RankingOut


class RecommendedListOut(BaseModel):
    items: list[RecommendedJobOut]
    total: int
    limit: int
    offset: int


FeedbackValue = Literal["positive", "negative", "interested", "notRelevant"]

_FEEDBACK_MAP: dict[str, MatchFeedback] = {
    "positive": MatchFeedback.POSITIVE,
    "negative": MatchFeedback.NEGATIVE,
    "interested": MatchFeedback.INTERESTED,
    "notRelevant": MatchFeedback.NOT_RELEVANT,
}

# Phase 16: the preference signal each feedback value also teaches, with its
# weight ("interested" is a weaker like).
_SIGNAL_MAP: dict[str, tuple[PreferenceSignalKind, float]] = {
    "positive": (PreferenceSignalKind.LIKE, 1.0),
    "interested": (PreferenceSignalKind.LIKE, 0.7),
    "negative": (PreferenceSignalKind.DISLIKE, -1.0),
    "notRelevant": (PreferenceSignalKind.NOT_RELEVANT, -2.0),
}


class FeedbackIn(BaseModel):
    feedback: FeedbackValue

    def to_enum(self) -> MatchFeedback:
        return _FEEDBACK_MAP[self.feedback]

    def to_signal(self) -> tuple[PreferenceSignalKind, float]:
        return _SIGNAL_MAP[self.feedback]


class HideIn(BaseModel):
    scope: Literal["company", "role"]

    def to_signal(self) -> PreferenceSignalKind:
        return (
            PreferenceSignalKind.HIDE_COMPANY
            if self.scope == "company"
            else PreferenceSignalKind.HIDE_ROLE
        )


def match_out(match: JobMatch) -> MatchOut:
    return MatchOut(
        jobId=match.jobId,
        overallScore=match.overallScore,
        componentScores=ComponentScoresOut(
            role=match.roleScore,
            skill=match.skillScore,
            experience=match.experienceScore,
            location=match.locationScore,
            salary=match.salaryScore,
            workMode=match.workModeScore,
            industry=match.industryScore,
            company=match.companyScore,
            watchlist=getattr(match, "watchlistScore", None),
        ),
        recommendation=match.recommendation,
        whyMatch=match.whyMatch,
        missingSkills=match.missingSkills,
        strengths=match.strengths,
        concerns=match.concerns,
        feedback=match.feedback,
        scoringVersion=match.scoringVersion,
        aiModel=match.aiModel,
        promptVersion=match.promptVersion,
        createdAt=match.createdAt,
        updatedAt=match.updatedAt,
    )


def recommended_out(ranked: RankedMatch) -> RecommendedJobOut:
    match = ranked.match
    assert match.job is not None
    job = job_out(match.job)
    job.ranking = ranked.ranking
    return RecommendedJobOut(job=job, match=match_out(match), ranking=ranked.ranking)
