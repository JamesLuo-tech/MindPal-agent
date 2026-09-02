"""小步行动 / 日程 API 路由。

GET    /api/schedule       - 日程列表（可选按状态筛选）
POST   /api/schedule       - 新增日程/微目标
PATCH  /api/schedule/{id}  - 更新（含标记完成）
DELETE /api/schedule/{id}  - 删除
"""
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth import get_current_user_id
from app.database import get_db
from app.schemas.goals import (
    ScheduleItemCreate,
    ScheduleItemOut,
    ScheduleItemUpdate,
    ScheduleStatus,
)

router = APIRouter()

_SELECT_FIELDS = "id, title, category, scheduled_at, status, completed_at, created_at"


@router.get("/schedule", response_model=list[ScheduleItemOut])
async def list_schedule(
    status: ScheduleStatus | None = Query(None),
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
):
    """返回当前用户的日程/微目标，可选按状态筛选。"""
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


@router.post("/schedule", response_model=ScheduleItemOut)
async def create_schedule_item(
    body: ScheduleItemCreate,
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
):
    """新增一条日程/微目标。"""
    row = await db.fetchrow(
        f"""
        INSERT INTO schedule_items (user_id, title, category, scheduled_at)
        VALUES ($1, $2, $3, $4)
        RETURNING {_SELECT_FIELDS}
        """,
        user_id,
        body.title,
        body.category,
        body.scheduled_at,
    )
    return ScheduleItemOut(**dict(row))


@router.patch("/schedule/{item_id}", response_model=ScheduleItemOut)
async def update_schedule_item(
    item_id: UUID,
    body: ScheduleItemUpdate,
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
):
    """部分更新一条日程/微目标（归属校验）；置为 done 时自动写 completed_at。"""
    owner = await db.fetchval("SELECT user_id FROM schedule_items WHERE id = $1", item_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="Schedule item not found")
    if str(owner) != str(user_id):
        raise HTTPException(status_code=403, detail="Not your schedule item")

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
        body.title,
        body.category,
        body.scheduled_at,
        body.status,
    )
    return ScheduleItemOut(**dict(row))


@router.delete("/schedule/{item_id}", status_code=204)
async def delete_schedule_item(
    item_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
):
    """删除一条日程/微目标（归属校验）。"""
    deleted = await db.fetchval(
        "DELETE FROM schedule_items WHERE id = $1 AND user_id = $2 RETURNING id",
        item_id,
        user_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Schedule item not found")
