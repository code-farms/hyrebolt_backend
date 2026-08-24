from typing import Literal

from pydantic import BaseModel


class ComponentStatus(BaseModel):
    name: str
    status: Literal["ok", "error"]
    detail: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    components: list[ComponentStatus]
