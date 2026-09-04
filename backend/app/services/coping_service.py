"""应对方法有效性记录（coping_results）的数据操作层。"""
from __future__ import annotations

from uuid import UUID

import asyncpg

from app.schemas.coping import CopingResultCreate, CopingResultOut


async def create_coping_result(
    user_id: UUID,
    payload: CopingResultCreate,
    db: asyncpg.Connection,
) -> CopingResultOut:
    row = await db.fetchrow(
        """
        INSERT INTO coping_results (user_id, method, helped, note)
        VALUES ($1, $2, $3, $4)
        RETURNING id, method, helped, note, created_at
        """,
        user_id,
        payload.method,
        payload.helped,
        payload.note,
    )
    return CopingResultOut(**dict(row))
