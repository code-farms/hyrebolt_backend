# camelCase wire contract, mirrored by the frontend zod schemas (Phase 15).
from datetime import datetime

from pydantic import BaseModel, Field

from app.db.generated.models import ApplicationDraft
from app.models import ApplicationDraftKind

MAX_DRAFT_CHARS = 20000


class DraftOut(BaseModel):
    kind: ApplicationDraftKind
    content: str
    generatedContent: str | None
    edited: bool
    # Generated with an older prompt or a resume other than the selected one.
    stale: bool
    resumeVersionId: str | None
    promptVersion: str | None
    model: str | None
    generatedAt: datetime | None
    editedAt: datetime | None
    createdAt: datetime
    updatedAt: datetime


class AssistantOut(BaseModel):
    jobId: str
    selectedResumeVersionId: str | None
    drafts: dict[ApplicationDraftKind, DraftOut | None]
    failed: list[ApplicationDraftKind] = Field(default_factory=list)


class GenerateIn(BaseModel):
    kinds: list[ApplicationDraftKind] | None = None  # default: every section
    force: bool = False  # regenerate sections that already have a draft


class SaveDraftIn(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_DRAFT_CHARS)


def draft_out(
    row: ApplicationDraft, *, current_prompt_version: str, selected_version_id: str | None
) -> DraftOut:
    generated = row.generatedContent is not None
    stale = generated and (
        row.promptVersion != current_prompt_version
        or (row.resumeVersionId or None) != (selected_version_id or None)
    )
    return DraftOut(
        kind=row.kind,
        content=row.content,
        generatedContent=row.generatedContent,
        edited=row.editedAt is not None,
        stale=stale,
        resumeVersionId=row.resumeVersionId,
        promptVersion=row.promptVersion,
        model=row.model,
        generatedAt=row.generatedAt,
        editedAt=row.editedAt,
        createdAt=row.createdAt,
        updatedAt=row.updatedAt,
    )
