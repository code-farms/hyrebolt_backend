
from app.core.config import get_settings
from app.models import RemotePreference
from app.schemas.analysis import JobAnalysisResult
from app.services.rule_based_matcher import NEUTRAL, RuleBasedMatcher
from tests.matching.fakes import make_match_job, make_profile

settings = get_settings()
matcher = RuleBasedMatcher(settings)


def analysis(**kwargs) -> JobAnalysisResult:
    return JobAnalysisResult.model_validate(kwargs)


def test_role_score_exact_partial_and_neutral() -> None:
    job = make_match_job(title="Backend Engineer")
    exact = make_profile(target_roles=["Backend Engineer"])
    partial = make_profile(target_roles=["Frontend Engineer"])
    none = make_profile(target_roles=[])

    _, exact_scores = matcher.score(exact, job, None)  # type: ignore[arg-type]
    _, partial_scores = matcher.score(partial, job, None)  # type: ignore[arg-type]
    _, none_scores = matcher.score(none, job, None)  # type: ignore[arg-type]

    assert exact_scores.role == 100.0
    assert 30 <= partial_scores.role < 100
    assert none_scores.role == NEUTRAL


def test_skill_score_via_analysis_required_and_preferred() -> None:
    job = make_match_job()
    result = analysis(skillsRequired=["python", "postgres"], skillsPreferred=["redis"])

    full = make_profile(skills=["Python", "Postgres", "Redis"])
    half = make_profile(skills=["Python"])
    none = make_profile(skills=[])

    assert matcher.score(full, job, result)[1].skill == 100.0  # type: ignore[arg-type]
    # covered 1.0 of total 2.5 -> 40
    assert matcher.score(half, job, result)[1].skill == 40.0  # type: ignore[arg-type]
    assert matcher.score(none, job, result)[1].skill == NEUTRAL  # type: ignore[arg-type]


def test_skill_score_falls_back_to_description() -> None:
    job = make_match_job(description="We use Python and PostgreSQL heavily")
    profile = make_profile(skills=["Python", "PostgreSQL"])

    score = matcher.score(profile, job, None)[1].skill  # type: ignore[arg-type]

    assert score > NEUTRAL


def test_experience_bands() -> None:
    profile = make_profile(years=4.0)
    in_range = make_match_job(experience_min=2, experience_max=6)
    below = make_match_job(experience_min=6)  # 2y gap -> 100-50
    above = make_match_job(experience_max=2)  # 2y over -> 100-20
    unknown = make_match_job()

    assert matcher.score(profile, in_range, None)[1].experience == 100.0  # type: ignore[arg-type]
    assert matcher.score(profile, below, None)[1].experience == 50.0  # type: ignore[arg-type]
    assert matcher.score(profile, above, None)[1].experience == 80.0  # type: ignore[arg-type]
    assert matcher.score(profile, unknown, None)[1].experience == NEUTRAL  # type: ignore[arg-type]


def test_experience_from_analysis_when_job_lacks_it() -> None:
    profile = make_profile(years=4.0)
    job = make_match_job()
    result = analysis(experienceMin=2, experienceMax=6)

    assert matcher.score(profile, job, result)[1].experience == 100.0  # type: ignore[arg-type]


def test_location_scores() -> None:
    remote_job = make_match_job(remote=True)
    local_job = make_match_job(location="Bengaluru, India")
    other_city = make_match_job(location="Pune, India")
    no_location = make_match_job(location=None)

    remote_lover = make_profile(remote_pref=RemotePreference.REMOTE)
    bengaluru = make_profile(locations=["Bengaluru"])

    assert matcher.score(remote_lover, remote_job, None)[1].location == 100.0  # type: ignore[arg-type]
    assert matcher.score(bengaluru, local_job, None)[1].location == 100.0  # type: ignore[arg-type]
    assert matcher.score(bengaluru, other_city, None)[1].location == 20.0  # type: ignore[arg-type]
    assert matcher.score(bengaluru, no_location, None)[1].location == NEUTRAL  # type: ignore[arg-type]


def test_salary_bands_and_currency() -> None:
    profile = make_profile(minimum_salary=2000000, preferred_salary=3000000)

    generous = make_match_job(salary_max=3500000, salary_currency="INR")
    acceptable = make_match_job(salary_max=2500000, salary_currency="INR")
    low = make_match_job(salary_max=1000000, salary_currency="INR")
    unknown = make_match_job()
    foreign = make_match_job(salary_max=90000, salary_currency="USD")

    assert matcher.score(profile, generous, None)[1].salary == 100.0  # type: ignore[arg-type]
    assert matcher.score(profile, acceptable, None)[1].salary == 70.0  # type: ignore[arg-type]
    assert matcher.score(profile, low, None)[1].salary == 20.0  # type: ignore[arg-type]
    assert matcher.score(profile, unknown, None)[1].salary == NEUTRAL  # type: ignore[arg-type]
    assert matcher.score(profile, foreign, None)[1].salary == NEUTRAL  # type: ignore[arg-type]


def test_work_mode_scores() -> None:
    remote_job = make_match_job(remote=True)
    hybrid_job = make_match_job(hybrid=True)
    onsite_via_analysis = make_match_job()
    onsite_analysis = analysis(workMode="ONSITE")

    remote_pref = make_profile(remote_pref=RemotePreference.REMOTE)
    any_pref = make_profile(remote_pref=RemotePreference.ANY)

    assert matcher.score(remote_pref, remote_job, None)[1].workMode == 100.0  # type: ignore[arg-type]
    assert matcher.score(remote_pref, hybrid_job, None)[1].workMode == 70.0  # type: ignore[arg-type]
    assert matcher.score(any_pref, remote_job, None)[1].workMode == 70.0  # type: ignore[arg-type]
    assert (
        matcher.score(remote_pref, onsite_via_analysis, onsite_analysis)[1].workMode == 0.0  # type: ignore[arg-type]
    )
    assert matcher.score(remote_pref, make_match_job(), None)[1].workMode == NEUTRAL  # type: ignore[arg-type]


def test_industry_and_company_scores() -> None:
    profile = make_profile(
        industries=["SaaS"],
        preferred_companies=["Acme"],
        excluded_companies=["Evil Corp"],
    )
    saas = analysis(industry="SaaS")
    fintech = analysis(industry="Fintech")

    preferred = make_match_job(company="Acme Inc.")
    excluded = make_match_job(company="Evil Corp")
    neutral = make_match_job(company="Globex")

    assert matcher.score(profile, preferred, saas)[1].industry == 100.0  # type: ignore[arg-type]
    assert matcher.score(profile, preferred, fintech)[1].industry == 0.0  # type: ignore[arg-type]
    assert matcher.score(profile, preferred, None)[1].company == 100.0  # type: ignore[arg-type]
    assert matcher.score(profile, excluded, None)[1].company == 0.0  # type: ignore[arg-type]
    assert matcher.score(profile, neutral, None)[1].company == NEUTRAL  # type: ignore[arg-type]


def test_overall_is_weighted_sum_and_deterministic() -> None:
    profile = make_profile(
        target_roles=["Backend Engineer"],
        skills=["Python"],
        years=4.0,
        remote_pref=RemotePreference.REMOTE,
    )
    job = make_match_job(remote=True, experience_min=2, experience_max=6)
    result = analysis(skillsRequired=["python"])

    overall1, c = matcher.score(profile, job, result)  # type: ignore[arg-type]
    overall2, _ = matcher.score(profile, job, result)  # type: ignore[arg-type]

    expected = (
        0.25 * c.role
        + 0.25 * c.skill
        + 0.15 * c.experience
        + 0.10 * c.location
        + 0.10 * c.salary
        + 0.05 * c.workMode
        + 0.05 * c.industry
        + 0.05 * c.company
    )
    assert overall1 == round(expected, 1)
    assert overall1 == overall2
    assert 0 <= overall1 <= 100


def test_weights_are_configurable() -> None:
    lopsided = get_settings().model_copy(
        update={
            "match_weight_role": 1.0,
            "match_weight_skills": 0.0,
            "match_weight_experience": 0.0,
            "match_weight_location": 0.0,
            "match_weight_salary": 0.0,
            "match_weight_work_mode": 0.0,
            "match_weight_industry": 0.0,
            "match_weight_company": 0.0,
        }
    )
    role_only = RuleBasedMatcher(lopsided)
    profile = make_profile(target_roles=["Backend Engineer"])
    job = make_match_job(title="Backend Engineer")

    overall, _ = role_only.score(profile, job, None)  # type: ignore[arg-type]

    assert overall == 100.0
