"""支持页（安全计划 + 可信联系人）的数据操作层。

从 api/support.py 抽出来，好让 REST 路由和 Agent 的写入工具调用同一套函数。
"""
from __future__ import annotations

from uuid import UUID

import asyncpg

from app.schemas.support import (
    SafetyPlanOut,
    SafetyPlanUpsert,
    TrustedContactCreate,
    TrustedContactOut,
)

_PLAN_FIELDS = (
    "warning_signs, internal_coping, distraction_people_places, "
    "help_contacts, professional_contacts, safe_environment, updated_at"
)


async def get_safety_plan(user_id: UUID, db: asyncpg.Connection) -> SafetyPlanOut | None:
    row = await db.fetchrow(
        f"SELECT {_PLAN_FIELDS} FROM safety_plans WHERE user_id = $1",
        user_id,
    )
    return SafetyPlanOut(**dict(row)) if row else None


async def save_safety_plan(
    user_id: UUID,
    payload: SafetyPlanUpsert,
    db: asyncpg.Connection,
) -> SafetyPlanOut:
    """创建或整体更新安全计划。只覆盖传入的（非 None）字段，其余保留原值。"""
    row = await db.fetchrow(
        f"""
        INSERT INTO safety_plans (
            user_id, warning_signs, internal_coping, distraction_people_places,
            help_contacts, professional_contacts, safe_environment
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (user_id) DO UPDATE SET
            warning_signs = COALESCE(EXCLUDED.warning_signs, safety_plans.warning_signs),
            internal_coping = COALESCE(EXCLUDED.internal_coping, safety_plans.internal_coping),
            distraction_people_places = COALESCE(EXCLUDED.distraction_people_places, safety_plans.distraction_people_places),
            help_contacts = COALESCE(EXCLUDED.help_contacts, safety_plans.help_contacts),
            professional_contacts = COALESCE(EXCLUDED.professional_contacts, safety_plans.professional_contacts),
            safe_environment = COALESCE(EXCLUDED.safe_environment, safety_plans.safe_environment),
            updated_at = NOW()
        RETURNING {_PLAN_FIELDS}
        """,
        user_id,
        payload.warning_signs,
        payload.internal_coping,
        payload.distraction_people_places,
        payload.help_contacts,
        payload.professional_contacts,
        payload.safe_environment,
    )
    return SafetyPlanOut(**dict(row))


async def list_trusted_contacts(user_id: UUID, db: asyncpg.Connection) -> list[TrustedContactOut]:
    rows = await db.fetch(
        """
        SELECT id, name, relationship, phone, created_at
        FROM trusted_contacts WHERE user_id = $1
        ORDER BY created_at
        """,
        user_id,
    )
    return [TrustedContactOut(**dict(r)) for r in rows]


async def create_trusted_contact(
    user_id: UUID,
    payload: TrustedContactCreate,
    db: asyncpg.Connection,
) -> TrustedContactOut:
    row = await db.fetchrow(
        """
        INSERT INTO trusted_contacts (user_id, name, relationship, phone)
        VALUES ($1, $2, $3, $4)
        RETURNING id, name, relationship, phone, created_at
        """,
        user_id,
        payload.name,
        payload.relationship,
        payload.phone,
    )
    return TrustedContactOut(**dict(row))


async def delete_trusted_contact(user_id: UUID, contact_id: UUID, db: asyncpg.Connection) -> bool:
    deleted = await db.fetchval(
        "DELETE FROM trusted_contacts WHERE id = $1 AND user_id = $2 RETURNING id",
        contact_id,
        user_id,
    )
    return bool(deleted)
