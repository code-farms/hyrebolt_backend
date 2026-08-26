from types import SimpleNamespace

from app.models import PreferenceSignalKind as K
from app.schemas.preferences import learned_preferences_out
from app.services.preference_signal_service import (
    MAX_ROLE_KEYS,
    SIGNAL_WEIGHTS,
    aggregate,
    snapshot,
)
from tests.ranking.fakes import FakeSignalRow, make_job, make_signal_service

USER = SimpleNamespace(id="u1")
OTHER = SimpleNamespace(id="u2")
ANALYSIS = {"skillsRequired": ["Python", "PostgreSQL"], "techStack": ["Docker"], "workMode": "HYBRID"}


def test_snapshot_normalises_keys_and_derives_work_mode() -> None:
    job = make_job(title="Senior Backend Engineer", company="Acme Pvt Ltd", remote=True)
    from app.schemas.analysis import JobAnalysisResult

    with_analysis = snapshot(job, JobAnalysisResult.model_validate(ANALYSIS))  # type: ignore[arg-type]
    assert with_analysis["roleKey"] == "senior backend engineer"
    assert with_analysis["companyKey"] == "acme" and with_analysis["companyLabel"] == "Acme Pvt Ltd"
    assert with_analysis["skills"] == ["python", "postgres", "docker"]  # aliased + deduped
    assert with_analysis["workMode"] == "HYBRID"  # analysis wins over the remote flag

    without = snapshot(job, None)  # type: ignore[arg-type]
    assert without["skills"] == [] and without["workMode"] == "REMOTE"


async def test_record_loads_analysis_and_verdicts_are_exclusive() -> None:
    job = make_job(job_id="j1")  # no analysis include, like the feedback/save routes
    service, repo = make_signal_service({"j1": ANALYSIS})

    liked = await service.record(USER, job, K.LIKE)  # type: ignore[arg-type]
    assert liked.skills == ["python", "postgres", "docker"] and liked.weight == 1.0

    await service.record(USER, job, K.DISLIKE)  # type: ignore[arg-type]
    kinds = {str(r.kind) for r in await repo.list_for_user("u1")}
    assert kinds == {"DISLIKE"}  # LIKE removed

    await service.record(USER, job, K.SAVE)  # type: ignore[arg-type]
    await service.record(USER, job, K.NOT_RELEVANT)  # type: ignore[arg-type]
    kinds = {str(r.kind) for r in await repo.list_for_user("u1")}
    assert kinds == {"SAVE", "NOT_RELEVANT"}  # SAVE is not part of the verdict group

    await service.remove(USER, job, K.SAVE)  # type: ignore[arg-type]
    assert {str(r.kind) for r in await repo.list_for_user("u1")} == {"NOT_RELEVANT"}


async def test_weight_override_reset_and_ownership() -> None:
    job = make_job(job_id="j1")
    service, repo = make_signal_service()
    row = await service.record(USER, job, K.LIKE, weight=0.7)  # type: ignore[arg-type]
    assert row.weight == 0.7
    hidden = await service.record(USER, job, K.HIDE_COMPANY)  # type: ignore[arg-type]
    assert hidden.weight == SIGNAL_WEIGHTS[K.HIDE_COMPANY] == 0.0

    assert await service.remove_signal(OTHER, hidden.id) is False  # type: ignore[arg-type]
    assert await service.remove_signal(USER, hidden.id) is True  # type: ignore[arg-type]
    assert await service.reset(USER) == 1  # type: ignore[arg-type]
    assert await repo.list_for_user("u1") == []


def _row(kind: K, weight: float, *, role="backend engineer", company="acme", skills=(), mode=None, loc=None):
    return FakeSignalRow(
        id=f"s-{kind}-{role}-{company}",
        userId="u1",
        jobId="j",
        kind=kind,
        weight=weight,
        roleKey=role,
        roleLabel=role.title(),
        companyId=None,
        companyKey=company,
        companyLabel=company.title(),
        locationKey=loc,
        workMode=mode,
        skills=list(skills),
    )


def test_aggregate_sums_weights_counts_and_hidden_lists() -> None:
    rows = [
        _row(K.SAVE, 1.5, skills=("python",), mode="REMOTE", loc="bengaluru"),
        _row(K.LIKE, 1.0, skills=("python", "docker"), mode="REMOTE"),
        _row(K.DISLIKE, -1.0, role="sales lead", company="globex"),
        _row(K.HIDE_COMPANY, 0.0, company="initech"),
        _row(K.HIDE_ROLE, 0.0, role="recruiter"),
    ]
    prefs = aggregate(rows)

    assert prefs.signal_count == 5
    backend = prefs.roles["backend engineer"]
    assert backend.weight == 2.5 and backend.count == 2
    assert backend.by_kind == {"SAVE": 1, "LIKE": 1}
    assert prefs.roles["sales lead"].weight == -1.0
    assert prefs.skills["python"].weight == 2.5 and prefs.skills["docker"].weight == 1.0
    assert prefs.companies["globex"].weight == -1.0
    assert prefs.work_modes["REMOTE"].weight == 2.5
    assert prefs.locations["bengaluru"].weight == 1.5
    assert [h.key for h in prefs.hidden_companies] == ["initech"]
    assert [h.label for h in prefs.hidden_roles] == ["Recruiter"]

    out = learned_preferences_out(prefs)
    assert out.preferredRoles[0].label == "Backend Engineer" and out.preferredRoles[0].weight == 2.5
    assert [a.key for a in out.dislikedRoles] == ["sales lead"]
    assert out.workModes == {"REMOTE": 2.5}
    assert out.hiddenCompanies[0].signalId.startswith("s-")


def test_aggregate_keeps_only_the_strongest_role_keys() -> None:
    rows = [_row(K.LIKE, 1.0, role=f"role {i}") for i in range(MAX_ROLE_KEYS + 5)]
    rows.append(_row(K.APPLY, 3.0, role="dream role"))
    prefs = aggregate(rows)
    assert len(prefs.roles) == MAX_ROLE_KEYS
    assert "dream role" in prefs.roles


def test_empty_preferences() -> None:
    prefs = aggregate([])
    assert prefs.is_empty and prefs.roles == {} and prefs.hidden_companies == ()
