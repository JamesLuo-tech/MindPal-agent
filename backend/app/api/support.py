"""支持 API 路由：安全计划 + 可信联系人。

GET/PUT         /api/support/safety-plan
GET/POST/DELETE /api/support/contacts

实际的数据操作在 services/support_service.py，Agent 的写入工具调用同一套函数。
"""
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user_id
from app.database import get_db
from app.schemas.support import (
    SafetyPlanOut,
    SafetyPlanUpsert,
    TrustedContactCreate,
    TrustedContactOut,
)
from app.services import support_service

router = APIRouter()


@router.get("/support/safety-plan", response_model=SafetyPlanOut | None)
async def get_safety_plan(
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
):
    """返回当前用户的安全计划；还没填过则返回 null，前端渲染空表单。"""
    return await support_service.get_safety_plan(user_id, db)


@router.put("/support/safety-plan", response_model=SafetyPlanOut)
async def save_safety_plan(
    body: SafetyPlanUpsert,
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
):
    """创建或更新安全计划。"""
    return await support_service.save_safety_plan(user_id, body, db)


@router.get("/support/contacts", response_model=list[TrustedContactOut])
async def list_trusted_contacts(
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
):
    """返回当前用户的可信联系人，按创建时间排序。"""
    return await support_service.list_trusted_contacts(user_id, db)


@router.post("/support/contacts", response_model=TrustedContactOut)
async def create_trusted_contact(
    body: TrustedContactCreate,
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
):
    """新增一位可信联系人。"""
    return await support_service.create_trusted_contact(user_id, body, db)


@router.delete("/support/contacts/{contact_id}", status_code=204)
async def delete_trusted_contact(
    contact_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
):
    """删除一位可信联系人（归属校验）。"""
    deleted = await support_service.delete_trusted_contact(user_id, contact_id, db)
    if not deleted:
        raise HTTPException(status_code=404, detail="Contact not found")
