"""今日 API 路由。

GET /api/today          - 今日快照（打卡 + 下一个日程 + 个性化推荐）
PUT /api/today/checkin  - 更新今日打卡
"""
from uuid import UUID

import asyncpg
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends

from app.core.auth import get_current_user_id
from app.database import get_db
from app.redis_client import get_redis
from app.schemas.today import CheckinUpsert, DailyCheckinOut, TodaySnapshotOut
from app.services.today_service import get_today_snapshot, upsert_checkin

router = APIRouter()


@router.get("/today", response_model=TodaySnapshotOut)
async def today_snapshot(
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """返回今天的打卡记录、下一个日程、个性化推荐。"""
    return await get_today_snapshot(user_id, db, redis)


@router.put("/today/checkin", response_model=DailyCheckinOut)
async def save_checkin(
    body: CheckinUpsert,
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
):
    """更新（或创建）今天的打卡记录，只覆盖本次传入的字段。"""
    return await upsert_checkin(user_id, body, db)
