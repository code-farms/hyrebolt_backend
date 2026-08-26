from types import SimpleNamespace

import pytest

from app.ai.exceptions import LLMUnavailableError
from app.core.config import get_settings
from app.core.exceptions import DependencyUnavailableError
from app.models import ApplicationDraftKind as K
from app.services.application_assistant_service import (
    PROMPT_VERSIONS,
    ApplicationAssistantService,
    DraftContent,
)
from tests.assistant.fakes import (
    ByKindProvider,
    FakeDraftRepository,
    FakeResumesForAssistant,
    make_job,
    make_version,
)
from tests.companies.fakes import FakeCompanyRepository
from tests.resumes.fakes import FakeSkillNames, make_profiles

USER = SimpleNamespace(id="u1")

OK = {
    K.COVER_LETTER: {"content": "Dear hiring team, I am applying for Platform Engineer at Globex."},
    K.RECRUITER_MESSAGE: {"content": "Hi — I'm a backend engineer interested in the Platform role."},
    K.RESUME_TAILORING: {"content": "- Move the Kubernetes migration to the top — the job needs it."},
    K.APPLICATION_NOTES: {"content": "Key requirements: Python, Kubernetes.\nGaps: Terraform."},
}


def make_service(provider, *, with_resume: bool = True):
    version = make_version() if with_resume else None
    settings = get_settings().model_copy(
        update={"llm_retry_base_delay_seconds": 0.0, "llm_timeout_seconds": 5.0}
    )
    drafts = FakeDraftRepository()
    companies = FakeCompanyRepository()
    service = ApplicationAssistantService(
        provider=provider,
        drafts=drafts,  # type: ignore[arg-type]
        profiles=make_profiles("u1", skills=["Python"]),  # type: ignore[arg-type]
        companies=companies,  # type: ignore[arg-type]
        resumes=FakeResumesForAssistant(version),  # type: ignore[arg-type]
        skills=FakeSkillNames(["Python", "Kubernetes", "Terraform"]),  # type: ignore[arg-type]
        settings=settings,
    )
    return service, drafts


async def test_generate_all_stores_provenance_and_grounded_prompt() -> None:
    provider = ByKindProvider(OK)
    service, drafts = make_service(provider)

    out = await service.generate(USER, make_job(), kinds=None, force=False)  # type: ignore[arg-type]

    assert out.failed == [] and out.selectedResumeVersionId == "v1"
    assert len(provider.calls) == 4
    for _kind, prompt in provider.calls:
        assert "Title: Platform Engineer" in prompt and "Backend Engineer at Acme Corp" in prompt
        assert "Matched: Python, Kubernetes" in prompt and "Missing: Terraform" in prompt
    cover = out.drafts[K.COVER_LETTER]
    assert cover is not None and cover.content.startswith("Dear hiring team")
    assert cover.generatedContent == cover.content
    assert cover.resumeVersionId == "v1"
    assert cover.promptVersion == PROMPT_VERSIONS[K.COVER_LETTER]
    assert cover.model == "scripted" and cover.generatedAt is not None
    assert cover.edited is False and cover.stale is False
    assert len(drafts.rows) == 4


async def test_generate_skips_existing_unless_forced() -> None:
    provider = ByKindProvider(OK)
    service, _ = make_service(provider)
    await service.generate(USER, make_job(), kinds=None, force=False)  # type: ignore[arg-type]

    again = await service.generate(USER, make_job(), kinds=None, force=False)  # type: ignore[arg-type]
    assert len(provider.calls) == 4 and again.failed == []

    await service.generate(USER, make_job(), kinds=[K.COVER_LETTER], force=True)  # type: ignore[arg-type]
    assert len(provider.calls) == 5 and provider.calls[-1][0] == K.COVER_LETTER


async def test_save_edit_and_regenerate_clears_it() -> None:
    provider = ByKindProvider(OK)
    service, _ = make_service(provider)
    job = make_job()
    await service.generate(USER, job, kinds=[K.COVER_LETTER], force=False)  # type: ignore[arg-type]

    saved = await service.save(USER, job, K.COVER_LETTER, "  My own version.  ")  # type: ignore[arg-type]
    assert saved.content == "My own version." and saved.edited is True
    assert saved.generatedContent == OK[K.COVER_LETTER]["content"]  # provenance kept

    regenerated = await service.generate(USER, job, kinds=[K.COVER_LETTER], force=True)  # type: ignore[arg-type]
    draft = regenerated.drafts[K.COVER_LETTER]
    assert draft is not None and draft.edited is False
    assert draft.content == OK[K.COVER_LETTER]["content"]


async def test_save_before_generate_creates_hand_written_draft() -> None:
    service, _ = make_service(ByKindProvider(OK))
    draft = await service.save(USER, make_job(), K.APPLICATION_NOTES, "Call recruiter Monday.")  # type: ignore[arg-type]
    assert draft.generatedContent is None and draft.model is None and draft.generatedAt is None
    assert draft.promptVersion is None and draft.edited is True and draft.stale is False


async def test_partial_failure_reports_kind_and_keeps_the_rest() -> None:
    responses = {**OK, K.RECRUITER_MESSAGE: LLMUnavailableError("down")}
    service, drafts = make_service(ByKindProvider(responses))

    out = await service.generate(USER, make_job(), kinds=None, force=False)  # type: ignore[arg-type]

    assert out.failed == [K.RECRUITER_MESSAGE]
    assert out.drafts[K.RECRUITER_MESSAGE] is None
    assert out.drafts[K.COVER_LETTER] is not None
    assert len(drafts.rows) == 3


async def test_all_failures_raise_503() -> None:
    responses = {kind: LLMUnavailableError("down") for kind in OK}
    service, _ = make_service(ByKindProvider(responses))
    with pytest.raises(DependencyUnavailableError):
        await service.generate(USER, make_job(), kinds=None, force=False)  # type: ignore[arg-type]


async def test_garbage_output_fails_only_that_kind() -> None:
    responses = {**OK, K.APPLICATION_NOTES: {"content": ""}}
    service, _ = make_service(ByKindProvider(responses))
    out = await service.generate(USER, make_job(), kinds=None, force=False)  # type: ignore[arg-type]
    assert out.failed == [K.APPLICATION_NOTES]


async def test_no_resume_selected_still_generates() -> None:
    service, _ = make_service(ByKindProvider(OK), with_resume=False)
    out = await service.generate(USER, make_job(), kinds=[K.COVER_LETTER], force=False)  # type: ignore[arg-type]
    draft = out.drafts[K.COVER_LETTER]
    assert out.selectedResumeVersionId is None
    assert draft is not None and draft.resumeVersionId is None and draft.stale is False


async def test_stale_when_selected_resume_changes() -> None:
    provider = ByKindProvider(OK)
    service, _ = make_service(provider)
    job = make_job()
    await service.generate(USER, job, kinds=[K.COVER_LETTER], force=False)  # type: ignore[arg-type]

    service._resumes = FakeResumesForAssistant(make_version(version_id="v2"))  # type: ignore[assignment]
    out = await service.get(USER, job)  # type: ignore[arg-type]
    draft = out.drafts[K.COVER_LETTER]
    assert draft is not None and draft.stale is True
    assert out.selectedResumeVersionId == "v2"


@pytest.mark.parametrize(
    "raw",
    [
        {"content": "```text\nDear team\n```"},
        {"content": '{"content": "Dear team"}'},
        {"text": "Dear team"},
        "Dear team",
    ],
)
def test_draft_content_unwraps_model_slips(raw: object) -> None:
    assert DraftContent.model_validate(raw).content == "Dear team"


def test_draft_content_rejects_empty_and_ambiguous() -> None:
    for raw in ({"content": "   "}, {"a": "x", "b": "y"}, {"content": 5}, None):
        with pytest.raises(ValueError):
            DraftContent.model_validate(raw)
