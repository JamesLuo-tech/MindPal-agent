"""goals_service 的单元测试：全部 mock db，只验证 SQL 参数和返回结构，不连真实数据库。"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

from app.services import goals_service
from app.schemas.goals import ScheduleItemCreate, ScheduleItemUpdate

USER_ID = uuid4()
ITEM_ID = uuid4()


def _row(**overrides):
    base = {
        "id": ITEM_ID,
        "title": "出门散步 10 分钟",
        "category": "walk",
        "scheduled_at": None,
        "status": "pending",
        "completed_at": None,
        "created_at": datetime.now(timezone.utc),
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_list_schedule_items_without_status_filter(mock_db):
    mock_db.fetch = AsyncMock(return_value=[_row()])

    result = await goals_service.list_schedule_items(USER_ID, mock_db)

    assert len(result) == 1
    assert result[0].title == "出门散步 10 分钟"
    args = mock_db.fetch.call_args.args
    assert args[1] == USER_ID
    assert "WHERE user_id = $1" in args[0]
    assert "status" not in args[0].split("WHERE")[1]  # 没传 status 就不该拼 status 条件


@pytest.mark.asyncio
async def test_list_schedule_items_with_status_filter(mock_db):
    mock_db.fetch = AsyncMock(return_value=[_row(status="done")])

    result = await goals_service.list_schedule_items(USER_ID, mock_db, status="done")

    assert result[0].status == "done"
    args = mock_db.fetch.call_args.args
    assert args[1] == USER_ID
    assert args[2] == "done"
    assert "AND status = $2" in args[0]


@pytest.mark.asyncio
async def test_create_schedule_item_passes_all_fields_in_order(mock_db):
    mock_db.fetchrow = AsyncMock(return_value=_row(title="喝一杯水", category="hydrate"))
    payload = ScheduleItemCreate(title="喝一杯水", category="hydrate", scheduled_at=None)

    result = await goals_service.create_schedule_item(USER_ID, payload, mock_db)

    assert result.title == "喝一杯水"
    args = mock_db.fetchrow.call_args.args
    # SQL, user_id, title, category, scheduled_at —— 位置必须对应 $1 $2 $3 $4
    assert args[1] == USER_ID
    assert args[2] == "喝一杯水"
    assert args[3] == "hydrate"
    assert args[4] is None


@pytest.mark.asyncio
async def test_update_schedule_item_returns_none_when_not_owner(mock_db):
    other_user = uuid4()
    mock_db.fetchval = AsyncMock(return_value=other_user)  # 记录存在，但属于别人

    result = await goals_service.update_schedule_item(
        USER_ID, ITEM_ID, ScheduleItemUpdate(status="done"), mock_db,
    )

    assert result is None
    mock_db.fetchrow.assert_not_called()  # 归属校验没过，不该执行 UPDATE


@pytest.mark.asyncio
async def test_update_schedule_item_returns_none_when_not_found(mock_db):
    mock_db.fetchval = AsyncMock(return_value=None)

    result = await goals_service.update_schedule_item(
        USER_ID, ITEM_ID, ScheduleItemUpdate(status="done"), mock_db,
    )

    assert result is None


@pytest.mark.asyncio
async def test_update_schedule_item_marks_done_when_owner(mock_db):
    mock_db.fetchval = AsyncMock(return_value=USER_ID)
    mock_db.fetchrow = AsyncMock(return_value=_row(status="done", completed_at=datetime.now(timezone.utc)))

    result = await goals_service.update_schedule_item(
        USER_ID, ITEM_ID, ScheduleItemUpdate(status="done"), mock_db,
    )

    assert result is not None
    assert result.status == "done"
    assert result.completed_at is not None


@pytest.mark.asyncio
async def test_delete_schedule_item_true_when_deleted(mock_db):
    mock_db.fetchval = AsyncMock(return_value=ITEM_ID)
    assert await goals_service.delete_schedule_item(USER_ID, ITEM_ID, mock_db) is True


@pytest.mark.asyncio
async def test_delete_schedule_item_false_when_nothing_deleted(mock_db):
    mock_db.fetchval = AsyncMock(return_value=None)
    assert await goals_service.delete_schedule_item(USER_ID, ITEM_ID, mock_db) is False
