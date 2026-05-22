"""周报 API 路由。

GET /api/reports/weekly - 生成本周情绪趋势报告
"""
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends

from app.core.auth import get_current_user_id
from app.database import get_db
from app.services.report_service import generate_weekly_report

router = APIRouter()


@router.get("/reports/weekly")
async def weekly_report(
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
):
    """生成近 7 天情绪趋势报告，包含每日数据、关键事件和 LLM 叙述摘要。"""
    return await generate_weekly_report(user_id, db)
