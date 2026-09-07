"""kb_candidate_service 的测试：聚合逻辑、prompt 拼接、LLM 输出解析全是
纯函数直接测；fetch/insert 两个碰数据库的函数用 mock_db 验证 SQL 和参数，
不连真实数据库。"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.kb_candidate_service import (
    build_kb_draft_prompt,
    fetch_uncovered_queries,
    group_uncovered_queries,
    insert_approved_candidate,
    parse_kb_draft_response,
)


def _mock_pool(conn: AsyncMock) -> MagicMock:
    """pool.acquire() 返回一个异步上下文管理器——AsyncMock() 本身会把 .acquire
    也变成一个 AsyncMock，调了之后拿到的是协程而不是上下文管理器，所以这里
    用 MagicMock 包一层，手动把 __aenter__/__aexit__ 接上，这是 mock 异步
    上下文管理器的标准写法。"""
    pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=None)
    pool.acquire.return_value = cm
    return pool


# ---------------------------------------------------------------------------
# group_uncovered_queries
# ---------------------------------------------------------------------------


def test_group_uncovered_queries_groups_exact_duplicates():
    rows = [
        {"id": uuid4(), "query": "跑步半小时消耗多少卡路里"},
        {"id": uuid4(), "query": "跑步半小时消耗多少卡路里"},
        {"id": uuid4(), "query": "失眠怎么办"},
    ]
    groups = group_uncovered_queries(rows, min_count=1)
    assert len(groups) == 2
    top = groups[0]
    assert top["query_text"] == "跑步半小时消耗多少卡路里"
    assert top["count"] == 2
    assert len(top["log_ids"]) == 2


def test_group_uncovered_queries_ignores_case_and_whitespace():
    rows = [
        {"id": uuid4(), "query": "CBT是什么"},
        {"id": uuid4(), "query": "  cbt是什么  "},
    ]
    groups = group_uncovered_queries(rows, min_count=1)
    assert len(groups) == 1
    assert groups[0]["count"] == 2


def test_group_uncovered_queries_filters_by_min_count():
    rows = [
        {"id": uuid4(), "query": "问过一次的问题"},
        {"id": uuid4(), "query": "问过两次的问题"},
        {"id": uuid4(), "query": "问过两次的问题"},
    ]
    groups = group_uncovered_queries(rows, min_count=2)
    assert len(groups) == 1
    assert groups[0]["query_text"] == "问过两次的问题"


def test_group_uncovered_queries_sorts_by_count_descending():
    rows = [
        {"id": uuid4(), "query": "A"},
        {"id": uuid4(), "query": "B"}, {"id": uuid4(), "query": "B"}, {"id": uuid4(), "query": "B"},
        {"id": uuid4(), "query": "C"}, {"id": uuid4(), "query": "C"},
    ]
    groups = group_uncovered_queries(rows, min_count=1)
    assert [g["query_text"] for g in groups] == ["B", "C", "A"]


def test_group_uncovered_queries_empty_input():
    assert group_uncovered_queries([], min_count=1) == []


def test_group_uncovered_queries_skips_empty_query_text():
    rows = [{"id": uuid4(), "query": "   "}]
    assert group_uncovered_queries(rows, min_count=1) == []


# ---------------------------------------------------------------------------
# build_kb_draft_prompt
# ---------------------------------------------------------------------------


def test_build_kb_draft_prompt_includes_query_and_material():
    prompt = build_kb_draft_prompt("失眠怎么办", "搜索到的资料内容")
    assert "失眠怎么办" in prompt
    assert "搜索到的资料内容" in prompt
    assert "不要编造" in prompt  # 防幻觉指令必须在


# ---------------------------------------------------------------------------
# parse_kb_draft_response
# ---------------------------------------------------------------------------


def test_parse_kb_draft_response_extracts_title_and_content():
    content = "标题: 失眠怎么缓解\n正文: 第一段内容。\n第二段内容。"
    result = parse_kb_draft_response(content)
    assert result == {"title": "失眠怎么缓解", "content": "第一段内容。\n第二段内容。"}


def test_parse_kb_draft_response_handles_chinese_colon():
    content = "标题：失眠怎么缓解\n正文：正文内容"
    result = parse_kb_draft_response(content)
    assert result["title"] == "失眠怎么缓解"
    assert result["content"] == "正文内容"


def test_parse_kb_draft_response_returns_none_when_missing_title():
    result = parse_kb_draft_response("正文: 只有正文没有标题")
    assert result is None


def test_parse_kb_draft_response_returns_none_when_missing_content():
    result = parse_kb_draft_response("标题: 只有标题没有正文")
    assert result is None


def test_parse_kb_draft_response_returns_none_on_garbage():
    assert parse_kb_draft_response("完全不按格式来的一段话") is None


# ---------------------------------------------------------------------------
# fetch_uncovered_queries（mock db）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_uncovered_queries_filters_by_web_source():
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[
        {"id": uuid4(), "query": "跑步消耗卡路里", "created_at": datetime.now(timezone.utc)},
    ])

    result = await fetch_uncovered_queries(_mock_pool(mock_conn))

    assert len(result) == 1
    sql = mock_conn.fetch.call_args.args[0]
    assert "source = 'web'" in sql


@pytest.mark.asyncio
async def test_fetch_uncovered_queries_applies_since_filter_when_given():
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])

    since = datetime(2026, 9, 1, tzinfo=timezone.utc)
    await fetch_uncovered_queries(_mock_pool(mock_conn), since=since)

    call_args = mock_conn.fetch.call_args.args
    assert "created_at >= $1" in call_args[0]
    assert call_args[1] == since


# ---------------------------------------------------------------------------
# insert_approved_candidate（mock db + mock embedding）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insert_approved_candidate_passes_correct_fields_in_order():
    mock_conn = AsyncMock()
    new_id = uuid4()
    mock_conn.fetchval = AsyncMock(return_value=new_id)

    with patch("app.agent.rag._encode", new=AsyncMock(return_value=[0.1, 0.2])):
        result = await insert_approved_candidate(
            _mock_pool(mock_conn), "auto_mined", "失眠怎么缓解", "正文内容", "网络搜索整理",
        )

    assert result == str(new_id)
    args = mock_conn.fetchval.call_args.args
    # SQL, topic, title, content, source, embedding, quality_score
    assert args[1] == "auto_mined"
    assert args[2] == "失眠怎么缓解"
    assert args[3] == "正文内容"
    assert args[4] == "网络搜索整理"
    assert args[6] == 0.8  # 默认 quality_score
