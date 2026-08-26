"""In-memory fakes for the Phase 15 application assistant."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from app.ai.base import LLMProvider, LLMResult
from app.models import ApplicationDraftKind
from app.services.application_assistant_service import SYSTEM_PROMPTS


@dataclass
class FakeDraftRow:
    id: str
    userId: str
    jobId: str
    kind: ApplicationDraftKind
    content: str
    generatedContent: str | None = None
    resumeVersionId: str | None = None
    promptVersion: str | None = None
    model: str | None = None
    generatedAt: datetime | None = None
    editedAt: datetime | None = None
    createdAt: datetime = field(default_factory=lambda: datetime.now(UTC))
    updatedAt: datetime = field(default_factory=lambda: datetime.now(UTC))


class FakeDraftRepository:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str], FakeDraftRow] = {}

    async def list_for_job(self, user_id: str, job_id: str) -> list[FakeDraftRow]:
        return [r for (u, j, _), r in self.rows.items() if u == user_id and j == job_id]

    async def get(self, user_id: str, job_id: str, kind: ApplicationDraftKind) -> FakeDraftRow | None:
        return self.rows.get((user_id, job_id, str(kind)))

    async def upsert_generated(
        self, user_id: str, job_id: str, kind: ApplicationDraftKind, **data: Any
    ) -> FakeDraftRow:
        row = self.rows.get((user_id, job_id, str(kind))) or FakeDraftRow(
            id=uuid.uuid4().hex, userId=user_id, jobId=job_id, kind=kind, content=""
        )
        row.content = data["content"]
        row.generatedContent = data["content"]
        row.resumeVersionId = data["resume_version_id"]
        row.promptVersion = data["prompt_version"]
        row.model = data["model"]
        row.generatedAt = data["generated_at"]
        row.editedAt = None
        row.updatedAt = datetime.now(UTC)
        self.rows[(user_id, job_id, str(kind))] = row
        return row

    async def upsert_content(
        self, user_id: str, job_id: str, kind: ApplicationDraftKind, *, content: str, edited_at: datetime
    ) -> FakeDraftRow:
        row = self.rows.get((user_id, job_id, str(kind))) or FakeDraftRow(
            id=uuid.uuid4().hex, userId=user_id, jobId=job_id, kind=kind, content=""
        )
        row.content = content
        row.editedAt = edited_at
        row.updatedAt = datetime.now(UTC)
        self.rows[(user_id, job_id, str(kind))] = row
        return row


class ByKindProvider(LLMProvider):
    """Answers per section (matched on the system prompt) and records every
    prompt, so tests can assert on the context the model was given."""

    def __init__(self, responses: dict[ApplicationDraftKind, dict[str, Any] | Exception]) -> None:
        self.responses = responses
        self.calls: list[tuple[ApplicationDraftKind, str]] = []

    async def complete_json(self, *, system: str, prompt: str) -> LLMResult:
        kind = next(k for k, s in SYSTEM_PROMPTS.items() if s == system)
        self.calls.append((kind, prompt))
        step = self.responses[kind]
        if isinstance(step, Exception):
            raise step
        return LLMResult(content=step, model="scripted", inputTokens=10, outputTokens=5)


class FakeResumesForAssistant:
    def __init__(self, version: Any | None) -> None:
        self.version = version

    async def selected_version(self, user):
        return self.version


def make_job(
    *,
    job_id: str = "j1",
    company_id: str | None = None,
    analysis: dict[str, Any] | None = None,
    description: str = "We need Python, Kubernetes and Terraform. Postgres a plus.",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=job_id,
        title="Platform Engineer",
        companyName="Globex",
        companyId=company_id,
        location="Bengaluru",
        remote=False,
        hybrid=True,
        description=description,
        deletedAt=None,
        analysis=SimpleNamespace(analysis=analysis) if analysis else None,
    )


def make_version(*, version_id: str = "v1", text: str = "Priya Sharma\nBackend Engineer at Acme Corp\nPython, PostgreSQL, Kubernetes") -> SimpleNamespace:
    return SimpleNamespace(
        id=version_id,
        resumeId="r1",
        extractedText=text,
        analysis=SimpleNamespace(
            analysis={
                "experience": [{"title": "Backend Engineer", "company": "Acme Corp", "startDate": "2020", "endDate": "2024"}],
                "skills": ["Python"],
                "technologies": ["PostgreSQL"],
                "achievements": ["Led the Kubernetes migration"],
            },
            processedAt=datetime.now(UTC),
        ),
    )
