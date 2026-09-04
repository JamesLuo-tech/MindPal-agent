from pydantic import BaseModel, Field
from datetime import datetime


class AppointmentSummaryRequest(BaseModel):
    days: int = Field(14, ge=1, le=90)
    discuss_topics: str | None = None


class AppointmentSummaryOut(BaseModel):
    period: str
    bullets: list[str]
    discuss_topics: str | None
    generated_at: datetime
