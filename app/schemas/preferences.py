# camelCase wire contract, mirrored by the frontend zod schemas (Phase 16).
from pydantic import BaseModel, Field

from app.services.preference_signal_service import (
    Affinity,
    LearnedPreferences,
    positive_and_negative,
)

TOP_N = 10


class AffinityOut(BaseModel):
    key: str
    label: str
    weight: float
    count: int
    byKind: dict[str, int]


class HiddenOut(BaseModel):
    signalId: str
    key: str
    label: str


class LearnedPreferencesOut(BaseModel):
    signalCount: int
    preferredRoles: list[AffinityOut]
    preferredSkills: list[AffinityOut]
    preferredCompanies: list[AffinityOut]
    preferredLocations: list[AffinityOut]
    dislikedRoles: list[AffinityOut]
    dislikedCompanies: list[AffinityOut]
    workModes: dict[str, float] = Field(default_factory=dict)
    hiddenCompanies: list[HiddenOut]
    hiddenRoles: list[HiddenOut]


def _affinity_out(affinity: Affinity) -> AffinityOut:
    return AffinityOut(
        key=affinity.key,
        label=affinity.label or affinity.key,
        weight=round(affinity.weight, 2),
        count=affinity.count,
        byKind=dict(affinity.by_kind),
    )


def learned_preferences_out(prefs: LearnedPreferences) -> LearnedPreferencesOut:
    roles_pos, roles_neg = positive_and_negative(prefs.roles, limit=TOP_N)
    skills_pos, _ = positive_and_negative(prefs.skills, limit=TOP_N)
    companies_pos, companies_neg = positive_and_negative(prefs.companies, limit=TOP_N)
    locations_pos, _ = positive_and_negative(prefs.locations, limit=TOP_N)
    return LearnedPreferencesOut(
        signalCount=prefs.signal_count,
        preferredRoles=[_affinity_out(a) for a in roles_pos],
        preferredSkills=[_affinity_out(a) for a in skills_pos],
        preferredCompanies=[_affinity_out(a) for a in companies_pos],
        preferredLocations=[_affinity_out(a) for a in locations_pos],
        dislikedRoles=[_affinity_out(a) for a in roles_neg],
        dislikedCompanies=[_affinity_out(a) for a in companies_neg],
        workModes={key: round(a.weight, 2) for key, a in prefs.work_modes.items()},
        hiddenCompanies=[
            HiddenOut(signalId=h.signal_id, key=h.key, label=h.label) for h in prefs.hidden_companies
        ],
        hiddenRoles=[
            HiddenOut(signalId=h.signal_id, key=h.key, label=h.label) for h in prefs.hidden_roles
        ],
    )
