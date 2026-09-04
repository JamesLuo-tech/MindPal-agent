"""小步行动 / 日程 API 路由。

GET    /api/schedule       - 日程列表（可选按状态筛选）
POST   /api/schedule       - 新增日程/微目标
PATCH  /api/schedule/{id}  - 更新（含标记完成）
DELETE /api/schedule/{id}  - 删除

实际的数据操作在 services/goals_service.py，Agent 的写入工具调用同一套函数。
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
from app.services import goals_service

router = APIRouter()


@router.get("/schedule", response_model=list[ScheduleItemOut])
async def list_schedule(
    status: ScheduleStatus | None = Query(None),
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
):
    """返回当前用户的日程/微目标，可选按状态筛选。"""
    return await goals_service.list_schedule_items(user_id, db, status)


@router.post("/schedule", response_model=ScheduleItemOut)
async def create_schedule_item(
    body: ScheduleItemCreate,
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
):
    """新增一条日程/微目标。"""
    return await goals_service.create_schedule_item(user_id, body, db)


@router.patch("/schedule/{item_id}", response_model=ScheduleItemOut)
async def update_schedule_item(
    item_id: UUID,
    body: ScheduleItemUpdate,
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
):
    """部分更新一条日程/微目标；置为 done 时自动写 completed_at。

    找不到或不属于当前用户统一报 404（不用 403 区分，避免暴露"这条记录属于别人"这个信息）。
    """
    result = await goals_service.update_schedule_item(user_id, item_id, body, db)
    if result is None:
        raise HTTPException(status_code=404, detail="Schedule item not found")
    return result


@router.delete("/schedule/{item_id}", status_code=204)
async def delete_schedule_item(
    item_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
):
    """删除一条日程/微目标（归属校验）。"""
    deleted = await goals_service.delete_schedule_item(user_id, item_id, db)
    if not deleted:
        raise HTTPException(status_code=404, detail="Schedule item not found")
