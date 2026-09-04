"""问诊摘要 API 路由。

POST /api/reports/appointment-summary - 生成一段自选时间范围内的自我记录要点，
供用户带去给医生/心理咨询师看。
"""
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends

from app.core.auth import get_current_user_id
from app.database import get_db
from app.schemas.summary import AppointmentSummaryOut, AppointmentSummaryRequest
from app.services.appointment_summary_service import generate_appointment_summary

router = APIRouter()


@router.post("/reports/appointment-summary", response_model=AppointmentSummaryOut)
async def appointment_summary(
    body: AppointmentSummaryRequest,
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
):
    return await generate_appointment_summary(user_id, body.days, body.discuss_topics, db)
