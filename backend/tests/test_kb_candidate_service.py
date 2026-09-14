"""kb_candidate_service 的测试。

设计对应用户给的企业级方案的两块：
  1. 限制来源 —— filter_trusted_results / assemble_candidate_content /
     build_classification_prompt / parse_classification_response
  2. 自动检查（不满足就暂不入库）—— check_source_trust / check_completeness /
     check_duplicate / check_claim_traceability / check_staleness /
     run_automated_checks
外加合并候选文件的 merge_candidates，以及碰数据库的 fetch/insert 三个函数
（mock db，不连真实数据库；真实端到端验证见
test_kb_candidate_integration.py）。
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.kb_candidate_service import (
    assemble_candidate_content,
    build_classification_prompt,
    check_claim_traceability,
    check_completeness,
    check_duplicate,
    check_source_trust,
    check_staleness,
    fetch_kb_contents,
    fetch_uncovered_queries,
    filter_trusted_results,
    group_uncovered_queries,
    insert_approved_candidate,
    merge_candidates,
    parse_classification_response,
    run_automated_checks,
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


def _segment(**overrides):
    base = {
        "text": "这是一段来自可信来源、长度足够的原文内容，用来测试用。",
        "source_url": "https://www.dxy.com/article/123",
        "source_domain": "dxy.com",
        "published_date": "2025-01-01",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# group_uncovered_queries（沿用 v1，行为不变）
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


def test_group_uncovered_queries_filters_by_min_count():
    rows = [
        {"id": uuid4(), "query": "问过一次的问题"},
        {"id": uuid4(), "query": "问过两次的问题"},
        {"id": uuid4(), "query": "问过两次的问题"},
    ]
    groups = group_uncovered_queries(rows, min_count=2)
    assert len(groups) == 1
    assert groups[0]["query_text"] == "问过两次的问题"


def test_group_uncovered_queries_empty_input():
    assert group_uncovered_queries([], min_count=1) == []


# ---------------------------------------------------------------------------
# filter_trusted_results —— 硬过滤可信域名
# ---------------------------------------------------------------------------


def test_filter_trusted_results_keeps_only_trusted_domains():
    organic = [
        {"link": "https://www.dxy.com/a", "snippet": "可信来源的内容", "displayed_link": "dxy.com", "date": "2025-01-01"},
        {"link": "https://randomblog.example.com/a", "snippet": "不可信来源的内容"},
    ]
    result = filter_trusted_results(organic)
    assert len(result) == 1
    assert result[0]["source_domain"] == "dxy.com"
    assert result[0]["text"] == "可信来源的内容"
    assert result[0]["source_url"] == "https://www.dxy.com/a"
    assert result[0]["published_date"] == "2025-01-01"


def test_filter_trusted_results_drops_untrusted_entirely():
    """不可信来源不是排后面，是根本不出现在结果里。"""
    organic = [{"link": "https://randomblog.example.com/a", "snippet": "内容"}]
    assert filter_trusted_results(organic) == []


def test_filter_trusted_results_skips_empty_snippet():
    organic = [{"link": "https://www.who.int/a", "snippet": "  "}]
    assert filter_trusted_results(organic) == []


def test_filter_trusted_results_respects_max_results():
    organic = [
        {"link": f"https://www.who.int/a{i}", "snippet": f"内容{i}"} for i in range(5)
    ]
    result = filter_trusted_results(organic, max_results=2)
    assert len(result) == 2


def test_filter_trusted_results_empty_input():
    assert filter_trusted_results([]) == []


# ---------------------------------------------------------------------------
# assemble_candidate_content —— 正文由原文拼接，不是自由生成
# ---------------------------------------------------------------------------


def test_assemble_candidate_content_includes_text_and_source():
    segments = [_segment(text="原文A"), _segment(text="原文B", source_url="https://who.int/b", published_date=None)]
    content = assemble_candidate_content(segments)
    assert "原文A" in content
    assert "原文B" in content
    assert "dxy.com" in content
    assert "发布日期未知" in content  # 没有日期时的兜底文案


# ---------------------------------------------------------------------------
# build_classification_prompt / parse_classification_response
# ---------------------------------------------------------------------------


def test_build_classification_prompt_includes_query_and_segments():
    prompt = build_classification_prompt("失眠怎么办", [_segment(text="原文内容")])
    assert "失眠怎么办" in prompt
    assert "原文内容" in prompt
    assert "不要总结或复述" in prompt


def test_parse_classification_response_extracts_title_and_keywords():
    content = "标题: 失眠的应对方法\n关键词: 失眠、睡眠卫生、入睡技巧"
    result = parse_classification_response(content)
    assert result == {"title": "失眠的应对方法", "keywords": ["失眠", "睡眠卫生", "入睡技巧"]}


def test_parse_classification_response_handles_chinese_colon_and_comma():
    content = "标题：CBT是什么\n关键词：认知行为疗法,CBT,心理治疗"
    result = parse_classification_response(content)
    assert result["title"] == "CBT是什么"
    assert result["keywords"] == ["认知行为疗法", "CBT", "心理治疗"]


def test_parse_classification_response_returns_none_when_missing_title():
    assert parse_classification_response("关键词: 失眠、睡眠") is None


def test_parse_classification_response_returns_none_on_garbage():
    assert parse_classification_response("完全不按格式来的一段话") is None


def test_parse_classification_response_ok_without_keywords_line():
    result = parse_classification_response("标题: 只有标题")
    assert result == {"title": "只有标题", "keywords": []}


# ---------------------------------------------------------------------------
# 自动检查：check_source_trust
# ---------------------------------------------------------------------------


def test_check_source_trust_passes_for_trusted_segments():
    result = check_source_trust([_segment()])
    assert result["passed"] is True


def test_check_source_trust_fails_when_no_segments():
    result = check_source_trust([])
    assert result["passed"] is False


def test_check_source_trust_fails_for_untrusted_domain():
    result = check_source_trust([_segment(source_domain="randomblog.example.com")])
    assert result["passed"] is False
    assert "不在允许列表" in result["detail"]


def test_check_source_trust_fails_when_missing_url():
    result = check_source_trust([_segment(source_url="")])
    assert result["passed"] is False


def test_check_source_trust_fails_when_empty_text():
    result = check_source_trust([_segment(text="  ")])
    assert result["passed"] is False


# ---------------------------------------------------------------------------
# 自动检查：check_completeness
# ---------------------------------------------------------------------------


def test_check_completeness_passes_for_long_enough_text():
    assert check_completeness([_segment()])["passed"] is True


def test_check_completeness_fails_for_short_text():
    result = check_completeness([_segment(text="太短")], min_chars=20)
    assert result["passed"] is False


# ---------------------------------------------------------------------------
# 自动检查：check_duplicate
# ---------------------------------------------------------------------------


def test_check_duplicate_passes_when_no_similar_content():
    result = check_duplicate("全新的内容，跟现有知识库完全不一样", ["完全不相关的另一条知识库内容"])
    assert result["passed"] is True


def test_check_duplicate_fails_for_near_identical_content():
    text = "晚上睡不着的时候可以试试以下几个方法来帮助自己入睡" * 3
    result = check_duplicate(text, [text])
    assert result["passed"] is False
    assert "疑似重复" in result["detail"]


def test_check_duplicate_passes_with_empty_existing():
    assert check_duplicate("任何内容", [])["passed"] is True


# ---------------------------------------------------------------------------
# 自动检查：check_claim_traceability
# ---------------------------------------------------------------------------


def test_check_claim_traceability_passes_when_content_built_from_segments():
    segments = [_segment(text="原文片段A")]
    content = assemble_candidate_content(segments)
    assert check_claim_traceability(content, segments)["passed"] is True


def test_check_claim_traceability_fails_when_content_diverges_from_segments():
    segments = [_segment(text="原文片段A")]
    content = "这是一段模型自由生成、跟原文对不上的内容"
    result = check_claim_traceability(content, segments)
    assert result["passed"] is False


# ---------------------------------------------------------------------------
# 自动检查：check_staleness
# ---------------------------------------------------------------------------


def test_check_staleness_passes_for_recent_date():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    segments = [_segment(published_date="2025-06-01")]
    assert check_staleness(segments, now=now)["passed"] is True


def test_check_staleness_fails_for_old_date():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    segments = [_segment(published_date="2020-01-01")]
    result = check_staleness(segments, stale_days=730, now=now)
    assert result["passed"] is False
    assert "过时" in result["detail"]


def test_check_staleness_fails_when_all_dates_unknown():
    """所有来源都没有发布日期时，保守起见不自动放行，而不是默认当成"新的"。"""
    segments = [_segment(published_date=None)]
    result = check_staleness(segments)
    assert result["passed"] is False
    assert "无法判断时效性" in result["detail"]


def test_check_staleness_fails_on_unparseable_date():
    segments = [_segment(published_date="不是一个日期")]
    assert check_staleness(segments)["passed"] is False


# ---------------------------------------------------------------------------
# run_automated_checks —— 全部通过才 all_passed
# ---------------------------------------------------------------------------


def test_run_automated_checks_all_pass():
    segments = [_segment()]
    candidate = {"segments": segments, "content": assemble_candidate_content(segments)}
    result = run_automated_checks(candidate, existing_kb_texts=["无关的现有内容"])
    assert result["all_passed"] is True
    assert set(result.keys()) == {
        "source_trust", "completeness", "dedup", "claim_traceability", "staleness", "all_passed",
    }


def test_run_automated_checks_fails_if_any_single_check_fails():
    segments = [_segment(source_domain="randomblog.example.com")]  # 来源不可信
    candidate = {"segments": segments, "content": assemble_candidate_content(segments)}
    result = run_automated_checks(candidate, existing_kb_texts=[])
    assert result["all_passed"] is False
    assert result["source_trust"]["passed"] is False


# ---------------------------------------------------------------------------
# merge_candidates —— 重新生成不覆盖已有候选
# ---------------------------------------------------------------------------


def test_merge_candidates_appends_only_new_queries():
    existing = [{"query_text": "已经存在的问题", "approved": True}]
    new = [
        {"query_text": "已经存在的问题", "approved": False},  # 应该被丢弃，不覆盖已有的
        {"query_text": "全新的问题", "approved": False},
    ]
    merged = merge_candidates(existing, new)
    assert len(merged) == 2
    assert merged[0]["approved"] is True  # 原来的没被覆盖
    assert merged[1]["query_text"] == "全新的问题"


def test_merge_candidates_is_case_and_whitespace_insensitive():
    existing = [{"query_text": "失眠怎么办"}]
    new = [{"query_text": "  失眠怎么办  "}]
    assert merge_candidates(existing, new) == existing


def test_merge_candidates_preserves_legacy_entries_without_segments():
    """旧格式（没有 segments 字段）的候选也要被当成"已存在"，不会被同名的
    新格式候选顶替掉。"""
    legacy = [{"query_text": "旧问题", "title": "旧标题", "approved": False}]
    new = [{"query_text": "旧问题", "title": "新标题", "segments": [], "approved": False}]
    merged = merge_candidates(legacy, new)
    assert merged == legacy


def test_merge_candidates_empty_existing():
    new = [{"query_text": "问题A"}]
    assert merge_candidates([], new) == new


# ---------------------------------------------------------------------------
# fetch_uncovered_queries / fetch_kb_contents（mock db）
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


@pytest.mark.asyncio
async def test_fetch_kb_contents_returns_active_content_list():
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[{"content": "内容A"}, {"content": "内容B"}])

    result = await fetch_kb_contents(_mock_pool(mock_conn))

    assert result == ["内容A", "内容B"]
    sql = mock_conn.fetch.call_args.args[0]
    assert "is_active = TRUE" in sql


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
            _mock_pool(mock_conn), "auto_mined", "失眠怎么缓解", "正文内容", "网络搜索（可信来源）",
            "https://www.dxy.com/a",
        )

    assert result == str(new_id)
    args = mock_conn.fetchval.call_args.args
    # SQL, topic, title, content, source, source_url, embedding, quality_score
    assert args[1] == "auto_mined"
    assert args[2] == "失眠怎么缓解"
    assert args[3] == "正文内容"
    assert args[4] == "网络搜索（可信来源）"
    assert args[5] == "https://www.dxy.com/a"
    assert args[7] == 0.8  # 默认 quality_score


@pytest.mark.asyncio
async def test_insert_approved_candidate_source_url_defaults_to_none():
    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=uuid4())

    with patch("app.agent.rag._encode", new=AsyncMock(return_value=[0.1, 0.2])):
        await insert_approved_candidate(
            _mock_pool(mock_conn), "auto_mined", "标题", "正文", "来源",
        )

    args = mock_conn.fetchval.call_args.args
    assert args[5] is None
