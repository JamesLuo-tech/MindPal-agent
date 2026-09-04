"""提议工具的参数契约测试：只验证每个 propose_* 工具接收的参数 schema 和
返回的 JSON 结构对不对，不碰数据库（这些工具本来就不该碰数据库）。"""
import json

import pytest

from app.agent.actions import ACTION_TOOL_NAMES, ACTION_TOOLS


def test_all_action_tools_are_registered_with_unique_names():
    assert len(ACTION_TOOLS) == 7
    assert len(ACTION_TOOL_NAMES) == 7  # 没有重名


def _invoke(tool, args: dict) -> dict:
    """调用工具并解析出结构化提议，顺带验证输出是合法 JSON。"""
    raw = tool.invoke(args)
    return json.loads(raw)


def test_propose_record_mood_only_fills_given_fields():
    result = _invoke_by_name("propose_record_mood", {"mood": 4, "energy": None, "sleep_hours": None, "small_win": None})
    assert result["action"] == "record_mood"
    assert result["params"] == {"mood": 4, "energy": None, "sleep_hours": None, "small_win": None}
    assert "心情 4/5" in result["summary"]


def test_propose_create_micro_action_requires_title():
    result = _invoke_by_name("propose_create_micro_action", {"title": "出门散步 10 分钟", "category": "walk"})
    assert result["action"] == "create_micro_action"
    assert result["params"]["title"] == "出门散步 10 分钟"
    assert result["params"]["scheduled_at"] is None  # 这个工具不负责定时间
    assert "出门散步" in result["summary"]


def test_propose_update_action_status_normalizes_invalid_status_to_done():
    result = _invoke_by_name("propose_update_action_status", {"title_hint": "散步", "status": "garbage"})
    assert result["params"]["status"] == "done"


def test_propose_update_action_status_accepts_skipped():
    result = _invoke_by_name("propose_update_action_status", {"title_hint": "散步", "status": "skipped"})
    assert result["params"]["status"] == "skipped"
    assert "跳过" in result["summary"]


def test_propose_schedule_checkin_defaults_to_240_minutes():
    result = _invoke_by_name("propose_schedule_checkin", {"note": "问问好点了没", "minutes_from_now": None})
    assert result["params"]["category"] == "checkin"
    assert result["params"]["scheduled_at"] is not None
    assert "晚些时候" in result["summary"]


def test_propose_schedule_checkin_respects_explicit_minutes():
    result = _invoke_by_name("propose_schedule_checkin", {"note": "问问好点了没", "minutes_from_now": 10})
    assert "10 分钟后" in result["summary"]


def test_propose_record_coping_result_summarizes_verdict():
    helped = _invoke_by_name("propose_record_coping_result", {"method": "深呼吸", "helped": True, "note": None})
    assert "有用" in helped["summary"]

    not_helped = _invoke_by_name("propose_record_coping_result", {"method": "深呼吸", "helped": False, "note": None})
    assert "没什么用" in not_helped["summary"]


def test_propose_save_memory_requires_summary_string():
    result = _invoke_by_name("propose_save_memory", {"summary": "用户喜欢用听音乐来缓解焦虑"})
    assert result["action"] == "save_memory"
    assert result["params"]["summary"] == "用户喜欢用听音乐来缓解焦虑"


def test_propose_update_safety_plan_only_includes_filled_fields_in_summary():
    result = _invoke_by_name("propose_update_safety_plan", {
        "warning_signs": "开始不想说话",
        "internal_coping": None,
        "distraction_people_places": None,
        "help_contacts": None,
        "professional_contacts": None,
        "safe_environment": None,
    })
    assert result["action"] == "update_safety_plan"
    assert "开始不想说话" in result["summary"]
    assert result["params"]["internal_coping"] is None


def _invoke_by_name(name: str, args: dict) -> dict:
    tool = next(t for t in ACTION_TOOLS if t.name == name)
    return _invoke(tool, args)


@pytest.mark.parametrize("name", sorted(ACTION_TOOL_NAMES))
def test_every_tool_has_a_docstring_description_for_the_llm(name):
    """每个工具都必须有清晰的 description，模型才知道什么时候该调用它。"""
    tool = next(t for t in ACTION_TOOLS if t.name == name)
    assert tool.description and len(tool.description) > 10
