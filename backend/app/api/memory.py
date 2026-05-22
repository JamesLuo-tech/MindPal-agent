"""记忆与情绪 API 路由。

GET    /api/memories          - 查看长期记忆列表
DELETE /api/memories/{id}     - 删除某条记忆
GET    /api/emotions?days=7   - 获取近 N 天情绪数据
"""
from datetime import datetime, timedelta, timezone
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth import get_current_user_id
from app.database import get_db
from app.schemas.memory import EmotionOut, MemoryOut

router = APIRouter()


@router.get("/memories", response_model=list[MemoryOut])
async def list_memories(
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
):
    """返回当前用户的长期向量记忆，最多 50 条，按时间倒序。"""
    rows = await db.fetch(
        """
        SELECT id, summary, created_at
        FROM memories
        WHERE user_id = $1
        ORDER BY created_at DESC
        LIMIT 50
        """,
        user_id,
    )
    return [
        MemoryOut(id=r["id"], summary=r["summary"], created_at=r["created_at"])
        for r in rows
    ]


@router.delete("/memories/{memory_id}", status_code=204)
async def delete_memory(
    memory_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
):
    """删除指定记忆（只能删除自己的）。"""
    deleted = await db.fetchval(
        "DELETE FROM memories WHERE id = $1 AND user_id = $2 RETURNING id",
        memory_id,
        user_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")


@router.get("/emotions", response_model=list[EmotionOut])
async def list_emotions(
    days: int = Query(7, ge=1, le=90),
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
):
    """返回近 N 天的情绪记录，供前端绘制情绪日历。"""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = await db.fetch(
        """
        SELECT id, primary_emotion, secondary_emotions, intensity, triggers, created_at
        FROM emotions
        WHERE user_id = $1 AND created_at >= $2
        ORDER BY created_at DESC
        """,
        user_id,
        since,
    )
    return [
        EmotionOut(
            id=r["id"],
            primary_emotion=r["primary_emotion"],
            secondary_emotions=r["secondary_emotions"] or [],
            intensity=r["intensity"],
            triggers=r["triggers"] or [],
            created_at=r["created_at"],
        )
        for r in rows
    ]
