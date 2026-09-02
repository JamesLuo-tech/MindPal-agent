from pydantic import BaseModel
from uuid import UUID
from datetime import date, datetime

from app.schemas.goals import ScheduleItemOut


class DailyCheckinOut(BaseModel):
    id: UUID
    checkin_date: date
    mood: int | None
    energy: int | None
    sleep_hours: float | None
    small_win: str | None
    created_at: datetime


class CheckinUpsert(BaseModel):
    mood: int | None = None
    energy: int | None = None
    sleep_hours: float | None = None
    small_win: str | None = None


class TodaySnapshotOut(BaseModel):
    checkin: DailyCheckinOut | None
    next_schedule_item: ScheduleItemOut | None
    recommendation: str
