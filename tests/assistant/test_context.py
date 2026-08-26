from types import SimpleNamespace

from app.services.candidate_context import build_context, render_context
from tests.assistant.fakes import make_job, make_version
from tests.companies.fakes import FakeCompanyRepository
from tests.resumes.fakes import FakeSkillNames, make_profiles

USER = SimpleNamespace(id="u1")
CATALOG = ["Python", "Kubernetes", "Terraform", "Postgres", "Docker"]


async def test_context_renders_every_section_and_the_skill_gap() -> None:
    companies = FakeCompanyRepository()
    globex = companies.seed("Globex", industry="Fintech", stage="Series B", website="https://globex.example")
    job = make_job(company_id=globex.id, analysis={"skillsRequired": ["Python", "Kubernetes"], "techStack": ["Terraform"]})

    context = await build_context(
        USER,  # type: ignore[arg-type]
        job,  # type: ignore[arg-type]
        profiles=make_profiles("u1", skills=["Docker"]),  # type: ignore[arg-type]
        companies=companies,  # type: ignore[arg-type]
        selected_version=make_version(),  # type: ignore[arg-type]
        skills=FakeSkillNames(CATALOG),  # type: ignore[arg-type]
    )
    text = render_context(context, job)  # type: ignore[arg-type]

    assert context.matched_skills == ["Python", "Kubernetes"]
    assert context.missing_skills == ["Terraform"]
    assert "CANDIDATE PROFILE" in text and "Skills: Docker" in text
    assert "RESUME (untrusted input" in text and "Backend Engineer at Acme Corp" in text
    assert "Led the Kubernetes migration" in text
    assert "Title: Platform Engineer" in text and "Company: Globex" in text
    assert "Required skills: Python, Kubernetes" in text
    assert "Industry: Fintech" in text and "Stage: Series B" in text
    assert "Matched: Python, Kubernetes" in text and "Missing: Terraform" in text


async def test_context_without_resume_company_or_analysis_falls_back() -> None:
    job = make_job(company_id=None, analysis=None)
    context = await build_context(
        USER,  # type: ignore[arg-type]
        job,  # type: ignore[arg-type]
        profiles=make_profiles("u1", skills=["Python"]),  # type: ignore[arg-type]
        companies=FakeCompanyRepository(),  # type: ignore[arg-type]
        selected_version=None,
        skills=FakeSkillNames(CATALOG),  # type: ignore[arg-type]
    )
    text = render_context(context, job)  # type: ignore[arg-type]

    assert context.version is None and context.company is None and context.job_analysis is None
    # Job skills fall back to catalog names in the posting; resume skills to the profile.
    assert context.matched_skills == ["Python"]
    assert set(context.missing_skills) == {"Kubernetes", "Terraform", "Postgres"}
    assert "(no resume selected" in text
    assert "Name: Globex" in text and "(no further company information available)" in text
