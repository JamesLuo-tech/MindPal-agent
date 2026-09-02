"""支持 API 路由：安全计划 + 可信联系人。

GET/PUT         /api/support/safety-plan
GET/POST/DELETE /api/support/contacts
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

router = APIRouter()

_PLAN_FIELDS = (
    "warning_signs, internal_coping, distraction_people_places, "
    "help_contacts, professional_contacts, safe_environment, updated_at"
)


@router.get("/support/safety-plan", response_model=SafetyPlanOut | None)
async def get_safety_plan(
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
):
    """返回当前用户的安全计划；还没填过则返回 null，前端渲染空表单。"""
    row = await db.fetchrow(
        f"SELECT {_PLAN_FIELDS} FROM safety_plans WHERE user_id = $1",
        user_id,
    )
    return SafetyPlanOut(**dict(row)) if row else None


@router.put("/support/safety-plan", response_model=SafetyPlanOut)
async def save_safety_plan(
    body: SafetyPlanUpsert,
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
):
    """创建或整体更新安全计划（表单一次性提交全部字段）。"""
    row = await db.fetchrow(
        f"""
        INSERT INTO safety_plans (
            user_id, warning_signs, internal_coping, distraction_people_places,
            help_contacts, professional_contacts, safe_environment
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (user_id) DO UPDATE SET
            warning_signs = EXCLUDED.warning_signs,
            internal_coping = EXCLUDED.internal_coping,
            distraction_people_places = EXCLUDED.distraction_people_places,
            help_contacts = EXCLUDED.help_contacts,
            professional_contacts = EXCLUDED.professional_contacts,
            safe_environment = EXCLUDED.safe_environment,
            updated_at = NOW()
        RETURNING {_PLAN_FIELDS}
        """,
        user_id,
        body.warning_signs,
        body.internal_coping,
        body.distraction_people_places,
        body.help_contacts,
        body.professional_contacts,
        body.safe_environment,
    )
    return SafetyPlanOut(**dict(row))


@router.get("/support/contacts", response_model=list[TrustedContactOut])
async def list_trusted_contacts(
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
):
    """返回当前用户的可信联系人，按创建时间排序。"""
    rows = await db.fetch(
        """
        SELECT id, name, relationship, phone, created_at
        FROM trusted_contacts WHERE user_id = $1
        ORDER BY created_at
        """,
        user_id,
    )
    return [TrustedContactOut(**dict(r)) for r in rows]


@router.post("/support/contacts", response_model=TrustedContactOut)
async def create_trusted_contact(
    body: TrustedContactCreate,
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
):
    """新增一位可信联系人。"""
    row = await db.fetchrow(
        """
        INSERT INTO trusted_contacts (user_id, name, relationship, phone)
        VALUES ($1, $2, $3, $4)
        RETURNING id, name, relationship, phone, created_at
        """,
        user_id,
        body.name,
        body.relationship,
        body.phone,
    )
    return TrustedContactOut(**dict(row))


@router.delete("/support/contacts/{contact_id}", status_code=204)
async def delete_trusted_contact(
    contact_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
):
    """删除一位可信联系人（归属校验）。"""
    deleted = await db.fetchval(
        "DELETE FROM trusted_contacts WHERE id = $1 AND user_id = $2 RETURNING id",
        contact_id,
        user_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Contact not found")
