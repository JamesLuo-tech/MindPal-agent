from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class MemoryOut(BaseModel):
    id: UUID
    summary: str
    created_at: datetime


class EmotionOut(BaseModel):
    id: UUID
    primary_emotion: str | None
    secondary_emotions: list
    intensity: int | None
    triggers: list
    created_at: datetime
