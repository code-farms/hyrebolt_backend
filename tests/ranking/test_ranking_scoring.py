from datetime import UTC, datetime

from app.models import MatchFeedback
from app.models import PreferenceSignalKind as K
from app.services.preference_signal_service import LearnedPreferences, aggregate
from app.services.ranking_service import DEFAULT_WEIGHTS, score_match, token_jaccard
from tests.ranking.fakes import FakeSignalRow, make_job, make_match

NOW = datetime.now(UTC)


def _row(kind: K, weight: float, **facts):
    base = {
        "id": "s",
        "userId": "u1",
        "jobId": "j",
        "kind": kind,
        "weight": weight,
        "roleKey": "backend engineer",
        "roleLabel": "Backend Engineer",
        "companyId": None,
        "companyKey": "acme",
        "companyLabel": "Acme",
        "locationKey": None,
        "workMode": None,
        "skills": [],
    }
    base.update(facts)
    return FakeSignalRow(**base)


def score(match, prefs=None, **kwargs):
    return score_match(match, prefs or LearnedPreferences(), now=NOW, weights=DEFAULT_WEIGHTS, **kwargs)


def test_no_signals_is_base_plus_freshness_only() -> None:
    match = make_match(make_job(discovered_days_ago=1.5), score=70)
    out = score(match)
    assert out is not None
    assert out.baseScore == 70 and out.preferenceScore == 0 and out.companyScore == 0
    assert out.freshnessScore == 6.0 and out.finalScore == 76.0
    assert out.explanations == ["Discovered yesterday"]


def test_freshness_tiers_prefer_posted_at() -> None:
    def fresh(**kw):
        return score(make_match(make_job(**kw), score=50)).freshnessScore  # type: ignore[union-attr]

    assert fresh(posted_days_ago=0.5) == 6.0
    assert fresh(posted_days_ago=5) == 4.0
    assert fresh(posted_days_ago=10) == 2.0
    assert fresh(posted_days_ago=40, discovered_days_ago=0.1) == 0.0  # postedAt wins
    job = make_job()
    job.postedAt = None
    job.discoveredAt = None
    assert score(make_match(job, score=50)).freshnessScore == 0.0  # type: ignore[union-attr]


def test_preference_from_roles_skills_company_location_and_mode() -> None:
    prefs = aggregate(
        [
            _row(K.APPLY, 3.0, id="a"),
            _row(K.SAVE, 1.5, id="b", skills=["python"], locationKey="bengaluru india", workMode="REMOTE"),
            _row(K.SAVE, 1.5, id="c", skills=["python"], locationKey="bengaluru india", workMode="REMOTE"),
        ]
    )
    job = make_job(
        title="Backend Engineer",
        company="Acme",
        remote=True,
        analysis={"skillsRequired": ["Python"], "techStack": []},
        posted_days_ago=30,
    )
    out = score(make_match(job, score=70), prefs)
    assert out is not None
    # roles 6 (strength 1 * cap 6) + skills 5 (3.0/3=1) + company 4 + location 3 + mode 3 = 21 → capped 15
    assert out.preferenceScore == 15.0
    assert out.finalScore == 85.0
    assert out.explanations[0].startswith("Ranked higher because you")
    assert any("roles like ‘Backend Engineer’" in e for e in out.explanations)
    assert len(out.explanations) <= 3


def test_similar_role_boost_is_weighted_and_negatives_rank_lower() -> None:
    prefs = aggregate([_row(K.DISLIKE, -1.0, id="d"), _row(K.NOT_RELEVANT, -2.0, id="e")])
    exact = score(make_match(make_job(title="Backend Engineer", company="Other", posted_days_ago=30), score=70), prefs)
    similar = score(make_match(make_job(title="Backend Engineer II", company="Other", posted_days_ago=30), score=70), prefs)
    unrelated = score(make_match(make_job(title="Product Designer", company="Other", posted_days_ago=30), score=70), prefs)
    assert exact is not None and similar is not None and unrelated is not None
    assert exact.preferenceScore == -6.0
    assert -6.0 < similar.preferenceScore < 0
    assert unrelated.preferenceScore == 0
    assert exact.explanations[0].startswith("Ranked lower because you dismissed")


def test_company_and_feedback_components() -> None:
    watch = score(make_match(make_job(posted_days_ago=30), score=70, watchlist_score=95, company_score=100))
    assert watch is not None and watch.companyScore == 5.0  # 5 + 3 capped at 5
    assert "Company is on your watchlist" in watch.explanations

    excluded = score(make_match(make_job(posted_days_ago=30), score=70, company_score=0))
    assert excluded is not None and excluded.companyScore == -10.0

    good = score(make_match(make_job(posted_days_ago=30), score=70, feedback=MatchFeedback.POSITIVE))
    bad = score(make_match(make_job(posted_days_ago=30), score=70, feedback=MatchFeedback.NEGATIVE))
    meh = score(make_match(make_job(posted_days_ago=30), score=70, feedback=MatchFeedback.INTERESTED))
    assert good is not None and good.feedbackScore == 5.0 and good.finalScore == 75.0
    assert bad is not None and bad.feedbackScore == -15.0 and bad.finalScore == 55.0
    assert meh is not None and meh.feedbackScore == 3.0


def test_base_dominates_and_final_is_clamped() -> None:
    strong = aggregate([_row(K.APPLY, 3.0, id="a") for _ in range(1)])
    high_base = score(make_match(make_job(title="Product Designer", company="Zed", posted_days_ago=30), score=90), strong)
    boosted_low = score(make_match(make_job(posted_days_ago=0.1), score=60, watchlist_score=95, feedback=MatchFeedback.POSITIVE), strong)
    assert high_base is not None and boosted_low is not None
    assert high_base.finalScore > boosted_low.finalScore
    maxed = score(make_match(make_job(posted_days_ago=0.1), score=99, feedback=MatchFeedback.POSITIVE), strong)
    assert maxed is not None and maxed.finalScore == 100.0


def test_hidden_company_and_role_exclusions() -> None:
    prefs = aggregate(
        [
            _row(K.HIDE_COMPANY, 0.0, id="h1", companyKey="initech", companyLabel="Initech"),
            _row(K.HIDE_ROLE, 0.0, id="h2", roleKey="senior backend engineer", roleLabel="Senior Backend Engineer"),
        ]
    )
    assert score(make_match(make_job(company="Initech Inc")), prefs) is None
    assert score(make_match(make_job(title="Senior Backend Engineer")), prefs) is None
    assert score(make_match(make_job(title="Senior Backend Engineer (Platform)")), prefs) is None  # jaccard 0.75
    assert score(make_match(make_job(title="Senior Frontend Engineer")), prefs) is not None  # 2/4 = 0.5
    assert score(make_match(make_job(title="Senior Backend Engineer")), prefs, exclude=False) is not None


def test_token_jaccard() -> None:
    assert token_jaccard("senior backend engineer", "senior backend engineer") == 1.0
    assert token_jaccard("senior backend engineer", "senior frontend engineer") == 0.5
    assert token_jaccard("", "x") == 0.0
