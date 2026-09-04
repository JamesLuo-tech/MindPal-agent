"""小步行动 / 日程的数据操作层。

从 api/goals.py 抽出来，好让 REST 路由和 Agent 的写入工具调用同一套函数，
不用为每个入口各写一遍 SQL。
"""
from __future__ import annotations

from uuid import UUID

import asyncpg

from app.schemas.goals import ScheduleItemCreate, ScheduleItemOut, ScheduleItemUpdate, ScheduleStatus

_SELECT_FIELDS = "id, title, category, scheduled_at, status, completed_at, created_at"


async def list_schedule_items(
    user_id: UUID,
    db: asyncpg.Connection,
    status: ScheduleStatus | None = None,
) -> list[ScheduleItemOut]:
    if status:
        rows = await db.fetch(
            f"""
            SELECT {_SELECT_FIELDS} FROM schedule_items
            WHERE user_id = $1 AND status = $2
            ORDER BY scheduled_at NULLS LAST, created_at
            """,
            user_id,
            status,
        )
    else:
        rows = await db.fetch(
            f"""
            SELECT {_SELECT_FIELDS} FROM schedule_items
            WHERE user_id = $1
            ORDER BY scheduled_at NULLS LAST, created_at
            """,
            user_id,
        )
    return [ScheduleItemOut(**dict(r)) for r in rows]


async def create_schedule_item(
    user_id: UUID,
    payload: ScheduleItemCreate,
    db: asyncpg.Connection,
) -> ScheduleItemOut:
    row = await db.fetchrow(
        f"""
        INSERT INTO schedule_items (user_id, title, category, scheduled_at)
        VALUES ($1, $2, $3, $4)
        RETURNING {_SELECT_FIELDS}
        """,
        user_id,
        payload.title,
        payload.category,
        payload.scheduled_at,
    )
    return ScheduleItemOut(**dict(row))


async def update_schedule_item(
    user_id: UUID,
    item_id: UUID,
    payload: ScheduleItemUpdate,
    db: asyncpg.Connection,
) -> ScheduleItemOut | None:
    """返回 None 表示这条记录不存在，或者不属于这个用户——由调用方决定报 404 还是 403。"""
    owner = await db.fetchval("SELECT user_id FROM schedule_items WHERE id = $1", item_id)
    if owner is None or str(owner) != str(user_id):
        return None

    row = await db.fetchrow(
        f"""
        UPDATE schedule_items SET
            title = COALESCE($2, title),
            category = COALESCE($3, category),
            scheduled_at = COALESCE($4, scheduled_at),
            status = COALESCE($5, status),
            completed_at = CASE
                WHEN $5 = 'done' THEN NOW()
                WHEN $5 IS NOT NULL THEN NULL
                ELSE completed_at
            END
        WHERE id = $1
        RETURNING {_SELECT_FIELDS}
        """,
        item_id,
        payload.title,
        payload.category,
        payload.scheduled_at,
        payload.status,
    )
    return ScheduleItemOut(**dict(row))


async def delete_schedule_item(user_id: UUID, item_id: UUID, db: asyncpg.Connection) -> bool:
    deleted = await db.fetchval(
        "DELETE FROM schedule_items WHERE id = $1 AND user_id = $2 RETURNING id",
        item_id,
        user_id,
    )
    return bool(deleted)
