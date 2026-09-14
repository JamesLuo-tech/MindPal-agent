"""crisis.py 的测试：关键词匹配、热线追加、危机事件审计日志写入。"""
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agent.crisis import (
    HOTLINE_APPEND,
    check_and_append_hotline,
    find_matched_keyword,
    save_crisis_event,
)


# ---------------------------------------------------------------------------
# find_matched_keyword
# ---------------------------------------------------------------------------


def test_find_matched_keyword_returns_first_match():
    assert find_matched_keyword("我最近特别难受，一点都不想活了") == "不想活"


def test_find_matched_keyword_returns_none_when_no_match():
    assert find_matched_keyword("今天天气不错") is None


# ---------------------------------------------------------------------------
# check_and_append_hotline
# ---------------------------------------------------------------------------


def test_check_and_append_hotline_triggers_and_appends_hotline():
    final, triggered, matched = check_and_append_hotline("我不想活了", "我在")
    assert triggered is True
    assert matched == "不想活"
    assert final == "我在" + HOTLINE_APPEND


def test_check_and_append_hotline_no_trigger_when_no_keyword():
    final, triggered, matched = check_and_append_hotline("今天挺开心的", "太好了")
    assert triggered is False
    assert matched is None
    assert final == "太好了"  # 没追加热线文案


# ---------------------------------------------------------------------------
# save_crisis_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_crisis_event_passes_correct_params(mock_db):
    user_id = uuid4()
    message_id = uuid4()
    mock_db.execute = AsyncMock()

    await save_crisis_event(user_id, message_id, "不想活", mock_db)

    args = mock_db.execute.call_args.args
    assert "INSERT INTO crisis_events" in args[0]
    assert args[1] == user_id
    assert args[2] == message_id
    assert args[3] == "不想活"


@pytest.mark.asyncio
async def test_save_crisis_event_allows_none_message_id(mock_db):
    """message_id 有可能是 None（比如消息持久化那一步失败了），
    不该因为这个直接崩，crisis_events.message_id 本身也允许为空
    （ON DELETE SET NULL）。"""
    mock_db.execute = AsyncMock()
    await save_crisis_event(uuid4(), None, "跳楼", mock_db)
    args = mock_db.execute.call_args.args
    assert args[2] is None
