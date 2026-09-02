from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Literal

ScheduleStatus = Literal["pending", "done", "skipped"]


class ScheduleItemOut(BaseModel):
    id: UUID
    title: str
    category: str | None
    scheduled_at: datetime | None
    status: ScheduleStatus
    completed_at: datetime | None
    created_at: datetime


class ScheduleItemCreate(BaseModel):
    title: str
    category: str | None = None
    scheduled_at: datetime | None = None


class ScheduleItemUpdate(BaseModel):
    title: str | None = None
    category: str | None = None
    scheduled_at: datetime | None = None
    status: ScheduleStatus | None = None
