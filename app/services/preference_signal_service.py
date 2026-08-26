"""Phase 16: feedback signals and the interpretable preferences learned from them.

A signal is one user action on one job (like, save, apply, hide…). The job's
facts are snapshotted onto the row, so `aggregate()` is a pure sum over the
user's own rows: every learned "preference" is a key, a signed weight and the
counts of the actions that produced it — nothing a user couldn't read back."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger
from app.db.generated.models import Job, User, UserPreferenceSignal
from app.models import PreferenceSignalKind
from app.repositories import JobAnalysisRepository, PreferenceSignalRepository
from app.schemas.analysis import JobAnalysisResult
from app.utils.normalization import normalize_company, normalize_skill, normalize_title

logger = get_logger(__name__)

SIGNAL_WEIGHTS: dict[PreferenceSignalKind, float] = {
    PreferenceSignalKind.LIKE: 1.0,
    PreferenceSignalKind.SAVE: 1.5,
    PreferenceSignalKind.APPLY: 3.0,
    PreferenceSignalKind.DISLIKE: -1.0,
    PreferenceSignalKind.NOT_RELEVANT: -2.0,
    PreferenceSignalKind.HIDE_COMPANY: 0.0,
    PreferenceSignalKind.HIDE_ROLE: 0.0,
}

# A job carries one verdict at a time (mirrors the single-valued JobMatch.feedback).
_VERDICT_KINDS = (
    PreferenceSignalKind.LIKE,
    PreferenceSignalKind.DISLIKE,
    PreferenceSignalKind.NOT_RELEVANT,
)
MAX_ROLE_KEYS = 20


@dataclass
class Affinity:
    key: str
    label: str
    weight: float = 0.0
    count: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)

    def add(self, kind: str, weight: float, label: str) -> None:
        self.weight += weight
        self.count += 1
        self.by_kind[kind] = self.by_kind.get(kind, 0) + 1
        if label and not self.label:
            self.label = label


@dataclass(frozen=True)
class HiddenItem:
    key: str
    label: str
    signal_id: str


@dataclass(frozen=True)
class LearnedPreferences:
    roles: dict[str, Affinity] = field(default_factory=dict)
    skills: dict[str, Affinity] = field(default_factory=dict)
    companies: dict[str, Affinity] = field(default_factory=dict)
    locations: dict[str, Affinity] = field(default_factory=dict)
    work_modes: dict[str, Affinity] = field(default_factory=dict)
    hidden_companies: tuple[HiddenItem, ...] = ()
    hidden_roles: tuple[HiddenItem, ...] = ()
    signal_count: int = 0

    @property
    def is_empty(self) -> bool:
        return self.signal_count == 0


def _kind_str(kind: object) -> str:
    return str(getattr(kind, "value", kind))


def aggregate(rows: Sequence[Any]) -> LearnedPreferences:
    """Pure aggregation of signal rows into learned preferences."""
    roles: dict[str, Affinity] = {}
    skills: dict[str, Affinity] = {}
    companies: dict[str, Affinity] = {}
    locations: dict[str, Affinity] = {}
    work_modes: dict[str, Affinity] = {}
    hidden_companies: dict[str, HiddenItem] = {}
    hidden_roles: dict[str, HiddenItem] = {}

    def bump(bucket: dict[str, Affinity], key: str | None, label: str, kind: str, weight: float) -> None:
        if not key:
            return
        bucket.setdefault(key, Affinity(key=key, label=label)).add(kind, weight, label)

    for row in rows:
        kind = _kind_str(row.kind)
        if kind == PreferenceSignalKind.HIDE_COMPANY:
            hidden_companies.setdefault(
                row.companyKey, HiddenItem(row.companyKey, row.companyLabel, row.id)
            )
            continue
        if kind == PreferenceSignalKind.HIDE_ROLE:
            hidden_roles.setdefault(row.roleKey, HiddenItem(row.roleKey, row.roleLabel, row.id))
            continue
        weight = float(row.weight)
        bump(roles, row.roleKey, row.roleLabel, kind, weight)
        bump(companies, row.companyKey, row.companyLabel, kind, weight)
        bump(locations, row.locationKey, row.locationKey or "", kind, weight)
        bump(work_modes, row.workMode, row.workMode or "", kind, weight)
        for skill in row.skills or []:
            bump(skills, skill, skill, kind, weight)

    # Bound the hot path and the Settings UI: keep the strongest role keys only.
    top_roles = dict(
        sorted(roles.items(), key=lambda item: abs(item[1].weight), reverse=True)[:MAX_ROLE_KEYS]
    )
    return LearnedPreferences(
        roles=top_roles,
        skills=skills,
        companies=companies,
        locations=locations,
        work_modes=work_modes,
        hidden_companies=tuple(hidden_companies.values()),
        hidden_roles=tuple(hidden_roles.values()),
        signal_count=len(rows),
    )


def derive_work_mode(job: Job, analysis: JobAnalysisResult | None) -> str | None:
    if analysis is not None and analysis.workMode:
        return str(analysis.workMode)
    if job.remote:
        return "REMOTE"
    if job.hybrid:
        return "HYBRID"
    return None


def snapshot(job: Job, analysis: JobAnalysisResult | None) -> dict[str, Any]:
    skills: list[str] = []
    if analysis is not None:
        seen: set[str] = set()
        for name in [*analysis.skillsRequired, *analysis.techStack]:
            key = normalize_skill(name)
            if key and key not in seen:
                seen.add(key)
                skills.append(key)
    return {
        # Application rows include the job without every column; fall back to
        # normalising the title ourselves.
        "roleKey": getattr(job, "normalizedTitle", None) or normalize_title(job.title),
        "roleLabel": job.title,
        "companyId": getattr(job, "companyId", None),
        "companyKey": normalize_company(job.companyName),
        "companyLabel": job.companyName,
        "locationKey": getattr(job, "normalizedLocation", None),
        "workMode": derive_work_mode(job, analysis),
        "skills": skills,
    }


class PreferenceSignalService:
    def __init__(
        self, signals: PreferenceSignalRepository, analyses: JobAnalysisRepository
    ) -> None:
        self._signals = signals
        self._analyses = analyses

    async def record(
        self,
        user: User,
        job: Job,
        kind: PreferenceSignalKind,
        *,
        weight: float | None = None,
    ) -> UserPreferenceSignal:
        if kind in _VERDICT_KINDS:
            others = [k for k in _VERDICT_KINDS if k != kind]
            await self._signals.delete_kinds(user.id, job.id, others)
        analysis = await self._load_analysis(job)
        data = {
            **snapshot(job, analysis),
            "weight": SIGNAL_WEIGHTS[kind] if weight is None else weight,
        }
        row = await self._signals.upsert(user.id, job.id, kind, data)
        logger.info("preference_signal_recorded", user_id=user.id, job_id=job.id, kind=str(kind))
        return row

    async def remove(self, user: User, job: Job, kind: PreferenceSignalKind) -> None:
        await self._signals.delete_kinds(user.id, job.id, [kind])

    async def remove_signal(self, user: User, signal_id: str) -> bool:
        return (await self._signals.delete_by_id(user.id, signal_id)) > 0

    async def reset(self, user: User) -> int:
        deleted = await self._signals.delete_all(user.id)
        logger.info("preference_signals_reset", user_id=user.id, deleted=deleted)
        return deleted

    async def learn(self, user: User) -> LearnedPreferences:
        return aggregate(await self._signals.list_for_user(user.id))

    async def _load_analysis(self, job: Job) -> JobAnalysisResult | None:
        row = getattr(job, "analysis", None)
        if row is None:
            row = await self._analyses.get_by_job_id(job.id)
        if row is None:
            return None
        try:
            return JobAnalysisResult.model_validate(row.analysis)
        except Exception:  # noqa: BLE001 - a corrupt stored analysis must not block feedback
            logger.warning("stored_analysis_invalid", job_id=job.id)
            return None


def positive_and_negative(
    bucket: dict[str, Affinity], *, limit: int
) -> tuple[list[Affinity], list[Affinity]]:
    """Top-N by weight in each direction, for the API summary."""
    positive = sorted((a for a in bucket.values() if a.weight > 0), key=lambda a: -a.weight)
    negative = sorted((a for a in bucket.values() if a.weight < 0), key=lambda a: a.weight)
    return positive[:limit], negative[:limit]
