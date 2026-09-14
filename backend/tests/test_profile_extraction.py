"""profile_extraction.py 的测试：解析逻辑（纯函数）+ 写入函数（mock db）。"""
import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agent.profile_extraction import (
    extract_profile_info,
    parse_profile_extraction,
    save_key_event,
    save_profile_updates,
)


# ---------------------------------------------------------------------------
# parse_profile_extraction
# ---------------------------------------------------------------------------


def test_parse_extracts_full_profile():
    content = json.dumps({
        "nickname": "小美", "age_range": "20-25", "diagnosis": "轻度焦虑", "key_event": None,
    }, ensure_ascii=False)
    result = parse_profile_extraction(content)
    assert result == {
        "nickname": "小美", "age_range": "20-25", "diagnosis": "轻度焦虑", "key_event": None,
    }


def test_parse_extracts_only_mentioned_fields():
    content = json.dumps({"nickname": "阿哲", "age_range": None, "diagnosis": None, "key_event": None})
    result = parse_profile_extraction(content)
    assert result["nickname"] == "阿哲"
    assert result["age_range"] is None
    assert result["diagnosis"] is None


def test_parse_extracts_key_event_with_valid_importance():
    content = json.dumps({
        "nickname": None, "age_range": None, "diagnosis": None,
        "key_event": {"event_type": "work", "content": "换了新工作", "importance": 7},
    }, ensure_ascii=False)
    result = parse_profile_extraction(content)
    assert result["key_event"] == {"event_type": "work", "content": "换了新工作", "importance": 7}


def test_parse_clamps_invalid_importance_to_default():
    content = json.dumps({
        "nickname": None, "age_range": None, "diagnosis": None,
        "key_event": {"event_type": "work", "content": "换了新工作", "importance": 99},
    }, ensure_ascii=False)
    result = parse_profile_extraction(content)
    assert result["key_event"]["importance"] == 5


def test_parse_clamps_non_integer_importance_to_default():
    content = json.dumps({
        "nickname": None, "age_range": None, "diagnosis": None,
        "key_event": {"event_type": "work", "content": "换了新工作", "importance": "很重要"},
    }, ensure_ascii=False)
    result = parse_profile_extraction(content)
    assert result["key_event"]["importance"] == 5


def test_parse_ignores_key_event_without_content():
    content = json.dumps({
        "nickname": None, "age_range": None, "diagnosis": None,
        "key_event": {"event_type": "work", "importance": 7},
    })
    result = parse_profile_extraction(content)
    assert result["key_event"] is None


def test_parse_defaults_missing_event_type_to_other():
    content = json.dumps({
        "nickname": None, "age_range": None, "diagnosis": None,
        "key_event": {"content": "分手了", "importance": 8},
    }, ensure_ascii=False)
    result = parse_profile_extraction(content)
    assert result["key_event"]["event_type"] == "other"


def test_parse_returns_empty_result_on_malformed_json():
    result = parse_profile_extraction("这不是 JSON")
    assert result == {"nickname": None, "age_range": None, "diagnosis": None, "key_event": None}


def test_parse_returns_empty_result_when_json_is_not_an_object():
    result = parse_profile_extraction("[1, 2, 3]")
    assert result == {"nickname": None, "age_range": None, "diagnosis": None, "key_event": None}


def test_parse_ignores_blank_string_fields():
    content = json.dumps({"nickname": "   ", "age_range": None, "diagnosis": None, "key_event": None})
    result = parse_profile_extraction(content)
    assert result["nickname"] is None


# ---------------------------------------------------------------------------
# extract_profile_info
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_profile_info_calls_llm_and_parses_response():
    mock_response = AsyncMock()
    mock_response.content = json.dumps({
        "nickname": "小美", "age_range": None, "diagnosis": None, "key_event": None,
    }, ensure_ascii=False)
    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    result = await extract_profile_info("你可以叫我小美", "好的小美", mock_llm)

    assert result["nickname"] == "小美"
    mock_llm.ainvoke.assert_awaited_once()
    sent_prompt = mock_llm.ainvoke.call_args.args[0]
    assert "你可以叫我小美" in sent_prompt
    assert "好的小美" in sent_prompt


# ---------------------------------------------------------------------------
# save_profile_updates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_profile_updates_skips_when_nothing_extracted(mock_db):
    mock_db.execute = AsyncMock()
    await save_profile_updates(
        uuid4(), {"nickname": None, "age_range": None, "diagnosis": None, "key_event": None}, mock_db,
    )
    mock_db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_profile_updates_upserts_with_coalesce(mock_db):
    user_id = uuid4()
    mock_db.execute = AsyncMock()

    await save_profile_updates(
        user_id, {"nickname": "小美", "age_range": None, "diagnosis": None, "key_event": None}, mock_db,
    )

    mock_db.execute.assert_awaited_once()
    args = mock_db.execute.call_args.args
    assert "ON CONFLICT (user_id) DO UPDATE" in args[0]
    assert "COALESCE" in args[0]
    assert args[1] == user_id
    assert args[2] == "小美"
    assert args[3] is None
    assert args[4] is None


# ---------------------------------------------------------------------------
# save_key_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_key_event_passes_correct_fields(mock_db):
    user_id = uuid4()
    mock_db.execute = AsyncMock()

    await save_key_event(
        user_id, {"event_type": "relationship", "content": "分手了", "importance": 8}, mock_db,
    )

    args = mock_db.execute.call_args.args
    assert "INSERT INTO key_events" in args[0]
    assert args[1] == user_id
    assert args[2] == "relationship"
    assert args[3] == "分手了"
    assert args[4] == 8
