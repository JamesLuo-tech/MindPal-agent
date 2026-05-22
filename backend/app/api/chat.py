"""对话相关 API 路由。

POST /api/conversations                        - 创建新会话
GET  /api/conversations                        - 获取会话列表
GET  /api/conversations/{id}/messages          - 获取消息列表
POST /api/chat                                 - 发送消息，SSE 流式返回
"""
from uuid import UUID

import asyncpg
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.core.auth import get_current_user_id
from app.database import get_db
from app.redis_client import get_redis
from app.schemas.chat import (
    ChatRequest,
    ConversationCreate,
    ConversationOut,
    MessageOut,
)
from app.services.chat_service import stream_chat

router = APIRouter()


@router.post("/conversations", response_model=ConversationOut)
async def create_conversation(
    body: ConversationCreate,
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
):
    """创建新会话，返回会话信息。"""
    row = await db.fetchrow(
        """
        INSERT INTO conversations (user_id, title)
        VALUES ($1, $2)
        RETURNING id, title, created_at
        """,
        user_id,
        body.title,
    )
    return ConversationOut(id=row["id"], title=row["title"], created_at=row["created_at"])


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
):
    """返回当前用户的所有会话，按创建时间倒序。"""
    rows = await db.fetch(
        """
        SELECT id, title, created_at
        FROM conversations
        WHERE user_id = $1
        ORDER BY created_at DESC
        """,
        user_id,
    )
    return [ConversationOut(id=r["id"], title=r["title"], created_at=r["created_at"]) for r in rows]


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conversation_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
):
    """返回指定会话的消息列表（验证归属后）。"""
    owner = await db.fetchval(
        "SELECT user_id FROM conversations WHERE id = $1",
        conversation_id,
    )
    if owner is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if str(owner) != str(user_id):
        raise HTTPException(status_code=403, detail="Not your conversation")

    rows = await db.fetch(
        """
        SELECT id, conversation_id, role, content, used_tools, created_at
        FROM messages
        WHERE conversation_id = $1
        ORDER BY created_at ASC
        """,
        conversation_id,
    )
    return [
        MessageOut(
            id=r["id"],
            conversation_id=r["conversation_id"],
            role=r["role"],
            content=r["content"],
            used_tools=r["used_tools"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


@router.post("/chat")
async def chat(
    body: ChatRequest,
    user_id: UUID = Depends(get_current_user_id),
    redis: aioredis.Redis = Depends(get_redis),
):
    """核心对话接口，SSE 流式返回。

    客户端监听事件：
      event: tool_use    data: {"tool": "...", "query": "...", "status": "searching"}
      event: tool_result data: {"tool": "...", "status": "done"}
      event: message     data: {"delta": "..."}
      event: done        data: {"message_id": "...", "crisis_triggered": false}
      event: error       data: {"code": "...", "message": "..."}
    """
    return StreamingResponse(
        stream_chat(user_id, body.conversation_id, body.message, redis),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
