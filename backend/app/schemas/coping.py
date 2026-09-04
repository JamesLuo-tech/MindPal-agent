from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class CopingResultCreate(BaseModel):
    method: str
    helped: bool | None = None
    note: str | None = None


class CopingResultOut(BaseModel):
    id: UUID
    method: str
    helped: bool | None
    note: str | None
    created_at: datetime
