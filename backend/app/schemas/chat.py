from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime


class ConversationCreate(BaseModel):
    title: str | None = None


class ConversationOut(BaseModel):
    id: UUID
    title: str | None
    created_at: datetime


class MessageOut(BaseModel):
    id: UUID
    conversation_id: UUID
    role: str
    content: str
    used_tools: list | None
    created_at: datetime


class ChatRequest(BaseModel):
    conversation_id: UUID
    message: str = Field(..., min_length=1, max_length=2000)


class ChatStreamEvent(BaseModel):
    event: str
    data: dict
