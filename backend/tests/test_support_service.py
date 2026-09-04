"""support_service 的单元测试：全部 mock db，只验证 SQL 参数和返回结构。"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

from app.services import support_service
from app.schemas.support import SafetyPlanUpsert, TrustedContactCreate

USER_ID = uuid4()
CONTACT_ID = uuid4()


@pytest.mark.asyncio
async def test_get_safety_plan_returns_none_when_not_created(mock_db):
    mock_db.fetchrow = AsyncMock(return_value=None)
    assert await support_service.get_safety_plan(USER_ID, mock_db) is None


@pytest.mark.asyncio
async def test_get_safety_plan_returns_parsed_plan(mock_db):
    mock_db.fetchrow = AsyncMock(return_value={
        "warning_signs": "开始不想说话",
        "internal_coping": None,
        "distraction_people_places": None,
        "help_contacts": None,
        "professional_contacts": None,
        "safe_environment": None,
        "updated_at": datetime.now(timezone.utc),
    })
    result = await support_service.get_safety_plan(USER_ID, mock_db)
    assert result.warning_signs == "开始不想说话"


@pytest.mark.asyncio
async def test_save_safety_plan_passes_fields_in_order(mock_db):
    mock_db.fetchrow = AsyncMock(return_value={
        "warning_signs": "开始失眠", "internal_coping": "听音乐",
        "distraction_people_places": None, "help_contacts": None,
        "professional_contacts": None, "safe_environment": None,
        "updated_at": datetime.now(timezone.utc),
    })
    payload = SafetyPlanUpsert(warning_signs="开始失眠", internal_coping="听音乐")

    result = await support_service.save_safety_plan(USER_ID, payload, mock_db)

    assert result.warning_signs == "开始失眠"
    args = mock_db.fetchrow.call_args.args
    assert args[1] == USER_ID
    assert args[2] == "开始失眠"
    assert args[3] == "听音乐"
    assert args[4] is None  # 没传的字段应该是 None，落到 SQL 里靠 COALESCE 保留原值


@pytest.mark.asyncio
async def test_list_trusted_contacts(mock_db):
    mock_db.fetch = AsyncMock(return_value=[
        {"id": CONTACT_ID, "name": "小李", "relationship": "朋友", "phone": "13800000000",
         "created_at": datetime.now(timezone.utc)},
    ])
    result = await support_service.list_trusted_contacts(USER_ID, mock_db)
    assert len(result) == 1
    assert result[0].name == "小李"


@pytest.mark.asyncio
async def test_create_trusted_contact_passes_fields_in_order(mock_db):
    mock_db.fetchrow = AsyncMock(return_value={
        "id": CONTACT_ID, "name": "小王", "relationship": None, "phone": None,
        "created_at": datetime.now(timezone.utc),
    })
    payload = TrustedContactCreate(name="小王")

    result = await support_service.create_trusted_contact(USER_ID, payload, mock_db)

    assert result.name == "小王"
    args = mock_db.fetchrow.call_args.args
    assert args[1] == USER_ID
    assert args[2] == "小王"
    assert args[3] is None
    assert args[4] is None


@pytest.mark.asyncio
async def test_delete_trusted_contact_true_when_deleted(mock_db):
    mock_db.fetchval = AsyncMock(return_value=CONTACT_ID)
    assert await support_service.delete_trusted_contact(USER_ID, CONTACT_ID, mock_db) is True


@pytest.mark.asyncio
async def test_delete_trusted_contact_false_when_nothing_deleted(mock_db):
    mock_db.fetchval = AsyncMock(return_value=None)
    assert await support_service.delete_trusted_contact(USER_ID, CONTACT_ID, mock_db) is False
