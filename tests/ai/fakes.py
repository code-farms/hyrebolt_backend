import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class FakeAnalysisRow:
    id: str
    jobId: str
    analysis: dict[str, Any]
    confidence: float | None
    model: str
    promptVersion: str
    inputTokens: int | None
    outputTokens: int | None
    processedAt: datetime
    createdAt: datetime = field(default_factory=lambda: datetime.now(UTC))


class FakeAnalysisRepository:
    def __init__(self) -> None:
        self.rows: dict[str, FakeAnalysisRow] = {}  # by jobId

    async def get_by_job_id(self, job_id: str) -> FakeAnalysisRow | None:
        return self.rows.get(job_id)

    async def upsert_for_job(self, job_id: str, **kwargs: Any) -> FakeAnalysisRow:
        row = FakeAnalysisRow(
            id=self.rows[job_id].id if job_id in self.rows else uuid.uuid4().hex,
            jobId=job_id,
            analysis=kwargs["analysis"],
            confidence=kwargs["confidence"],
            model=kwargs["model"],
            promptVersion=kwargs["prompt_version"],
            inputTokens=kwargs["input_tokens"],
            outputTokens=kwargs["output_tokens"],
            processedAt=kwargs["processed_at"],
        )
        self.rows[job_id] = row
        return row


@dataclass
class FakeJob:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    title: str = "Backend Engineer"
    companyName: str = "Acme"
    location: str | None = "Bengaluru, India"
    remote: bool = False
    hybrid: bool = False
    description: str | None = "Build APIs with Python. 3+ years required."
    deletedAt: datetime | None = None


class FakeJobsForAnalysis:
    def __init__(self, jobs: list[FakeJob]) -> None:
        self.jobs = jobs
        self.analyses: FakeAnalysisRepository | None = None

    async def find_unanalyzed(self, prompt_version: str, *, limit: int) -> list[FakeJob]:
        assert self.analyses is not None
        result = []
        for job in self.jobs:
            row = self.analyses.rows.get(job.id)
            if row is None or row.promptVersion != prompt_version:
                result.append(job)
        return result[:limit]
