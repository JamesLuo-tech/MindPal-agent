"""确认后执行（ACTION_DISPATCH）的契约测试：验证每个 action 名都能把
前端传回来的 params 正确转成 pydantic 模型、传给对应的 service 函数——
mock 掉 service 层，只测"接口参数对不对"，不连真实数据库。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.agent import actions

USER_ID = uuid4()


@pytest.mark.asyncio
async def test_record_mood_dispatches_to_today_service_with_validated_payload(mock_db):
    with patch.object(actions.today_service, "upsert_checkin", new=AsyncMock()) as mocked:
        mocked.return_value.model_dump = MagicMock(return_value={"mood": 4})
        await actions.ACTION_DISPATCH["record_mood"](
            USER_ID, {"mood": 4, "energy": None, "sleep_hours": None, "small_win": None}, mock_db,
        )
        called_user_id, called_payload, called_db = mocked.call_args.args
        assert called_user_id == USER_ID
        assert called_payload.mood == 4
        assert called_db is mock_db


@pytest.mark.asyncio
async def test_record_mood_rejects_out_of_range_mood(mock_db):
    """mood 超出 1-5，交给 pydantic schema 的校验来挡，不该走到 service 那一层。"""
    with pytest.raises(Exception):
        await actions.ACTION_DISPATCH["record_mood"](
            USER_ID, {"mood": 99, "energy": None, "sleep_hours": None, "small_win": None}, mock_db,
        )


@pytest.mark.asyncio
async def test_create_micro_action_dispatches_with_title(mock_db):
    with patch.object(actions.goals_service, "create_schedule_item", new=AsyncMock()) as mocked:
        mocked.return_value.model_dump = MagicMock(return_value={"title": "散步"})
        await actions.ACTION_DISPATCH["create_micro_action"](
            USER_ID, {"title": "出门散步 10 分钟", "category": "walk", "scheduled_at": None}, mock_db,
        )
        called_payload = mocked.call_args.args[1]
        assert called_payload.title == "出门散步 10 分钟"
        assert called_payload.category == "walk"


@pytest.mark.asyncio
async def test_create_micro_action_requires_title_field():
    with pytest.raises(Exception):
        await actions.ACTION_DISPATCH["create_micro_action"](
            USER_ID, {"category": "walk", "scheduled_at": None}, AsyncMock(),
        )


@pytest.mark.asyncio
async def test_update_action_status_returns_error_dict_when_no_match(mock_db):
    mock_db.fetchrow = AsyncMock(return_value=None)

    result = await actions.ACTION_DISPATCH["update_action_status"](
        USER_ID, {"title_hint": "根本不存在的事", "status": "done"}, mock_db,
    )

    assert "error" in result
    mock_db.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_update_action_status_updates_matched_item(mock_db):
    item_id = uuid4()
    mock_db.fetchrow = AsyncMock(return_value={"id": item_id})
    with patch.object(actions.goals_service, "update_schedule_item", new=AsyncMock()) as mocked:
        mocked.return_value.model_dump = MagicMock(return_value={"status": "done"})
        await actions.ACTION_DISPATCH["update_action_status"](
            USER_ID, {"title_hint": "散步", "status": "done"}, mock_db,
        )
        called_user_id, called_item_id, called_payload, called_db = mocked.call_args.args
        assert called_item_id == item_id
        assert called_payload.status == "done"


@pytest.mark.asyncio
async def test_schedule_checkin_dispatches_as_a_schedule_item(mock_db):
    with patch.object(actions.goals_service, "create_schedule_item", new=AsyncMock()) as mocked:
        mocked.return_value.model_dump = MagicMock(return_value={})
        await actions.ACTION_DISPATCH["schedule_checkin"](
            USER_ID, {"title": "问问好点了没", "category": "checkin", "scheduled_at": "2026-09-02T20:00:00+00:00"}, mock_db,
        )
        called_payload = mocked.call_args.args[1]
        assert called_payload.category == "checkin"


@pytest.mark.asyncio
async def test_record_coping_result_dispatches_with_helped_flag(mock_db):
    with patch.object(actions.coping_service, "create_coping_result", new=AsyncMock()) as mocked:
        mocked.return_value.model_dump = MagicMock(return_value={})
        await actions.ACTION_DISPATCH["record_coping_result"](
            USER_ID, {"method": "深呼吸", "helped": True, "note": None}, mock_db,
        )
        called_payload = mocked.call_args.args[1]
        assert called_payload.method == "深呼吸"
        assert called_payload.helped is True


@pytest.mark.asyncio
async def test_save_memory_calls_vector_memory_with_pool_not_connection(mock_db):
    with patch.object(actions, "_save_memory_to_vector", new=AsyncMock()) as mocked, \
         patch.object(actions._db, "_pool", "fake-pool-object"):
        result = await actions.ACTION_DISPATCH["save_memory"](
            USER_ID, {"summary": "用户喜欢听音乐缓解焦虑"}, mock_db,
        )
        mocked.assert_called_once_with(USER_ID, "用户喜欢听音乐缓解焦虑", "fake-pool-object")
        assert result == {"summary": "用户喜欢听音乐缓解焦虑"}


@pytest.mark.asyncio
async def test_update_safety_plan_dispatches_with_only_provided_fields(mock_db):
    with patch.object(actions.support_service, "save_safety_plan", new=AsyncMock()) as mocked:
        mocked.return_value.model_dump = MagicMock(return_value={})
        await actions.ACTION_DISPATCH["update_safety_plan"](
            USER_ID,
            {
                "warning_signs": "开始不想说话", "internal_coping": None,
                "distraction_people_places": None, "help_contacts": None,
                "professional_contacts": None, "safe_environment": None,
            },
            mock_db,
        )
        called_payload = mocked.call_args.args[1]
        assert called_payload.warning_signs == "开始不想说话"
        assert called_payload.internal_coping is None


def test_every_action_tool_has_a_matching_dispatch_entry():
    """每个 propose 工具的 action 名，都必须在 ACTION_DISPATCH 里有对应的执行函数，
    不然确认按钮点了会 400——这是防止两边加了工具却忘了接执行逻辑的回归测试。"""
    from app.agent.actions import ACTION_TOOLS
    import json

    for t in ACTION_TOOLS:
        # 用工具名反推 action 名（去掉 propose_ 前缀）
        action_name = t.name.removeprefix("propose_")
        assert action_name in actions.ACTION_DISPATCH, f"{t.name} 没有对应的 ACTION_DISPATCH 执行函数"
