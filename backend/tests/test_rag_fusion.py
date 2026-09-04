"""RAG Fusion + RRF 的正确性测试：查询改写、倒数排名融合打分、并发检索编排。

不碰真实数据库/LLM——generate_query_variants 依赖的 get_llm() 和
rag_fusion_search 依赖的 rag_search() 全部 mock 掉，只验证这几个函数
自己的逻辑（融合打分对不对、并发调用有没有漏查询变体）。
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.rag import (
    _reciprocal_rank_fusion,
    generate_query_variants,
    rag_fusion_search,
)


# ---------------------------------------------------------------------------
# _reciprocal_rank_fusion
# ---------------------------------------------------------------------------


def test_rrf_empty_input_returns_empty_list():
    assert _reciprocal_rank_fusion([]) == []
    assert _reciprocal_rank_fusion([[], []]) == []


def test_rrf_ranks_doc_appearing_in_multiple_lists_higher():
    """在多个变体检索里都排前面的文档，融合后应该排到最前面。"""
    results_list = [
        [{"id": "a", "score": 0.9}, {"id": "b", "score": 0.5}, {"id": "c", "score": 0.4}],
        [{"id": "b", "score": 0.85}],
    ]
    fused = _reciprocal_rank_fusion(results_list, k=60)
    assert [d["id"] for d in fused] == ["b", "a", "c"]


def test_rrf_keeps_last_seen_doc_payload_for_overlapping_ids():
    """同一篇文档在不同变体里的相似度分数不同，doc_map 保留最后一次出现时的完整记录。"""
    results_list = [
        [{"id": "b", "score": 0.5}],
        [{"id": "b", "score": 0.85}],
    ]
    fused = _reciprocal_rank_fusion(results_list)
    assert fused == [{"id": "b", "score": 0.85}]


def test_rrf_single_list_preserves_original_order():
    results_list = [[{"id": "x", "score": 0.9}, {"id": "y", "score": 0.8}]]
    fused = _reciprocal_rank_fusion(results_list)
    assert [d["id"] for d in fused] == ["x", "y"]


# ---------------------------------------------------------------------------
# generate_query_variants
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_query_variants_includes_original_query_first():
    mock_response = AsyncMock()
    mock_response.content = "焦虑引起的失眠怎么办\n晚上睡不着和焦虑有关吗\n如何缓解焦虑性失眠"

    with patch("app.agent.llm.get_llm") as mock_get_llm:
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_get_llm.return_value = mock_llm
        variants = await generate_query_variants("焦虑睡不着")

    assert variants[0] == "焦虑睡不着"
    assert len(variants) == 4  # 原始问题 + 3 条改写
    assert "焦虑引起的失眠怎么办" in variants


@pytest.mark.asyncio
async def test_generate_query_variants_caps_at_three_even_with_more_lines():
    mock_response = AsyncMock()
    mock_response.content = "v1\nv2\nv3\nv4\nv5"

    with patch("app.agent.llm.get_llm") as mock_get_llm:
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_get_llm.return_value = mock_llm
        variants = await generate_query_variants("原始问题")

    assert len(variants) == 4  # 原始 + 最多 3 条改写，多出的行被截掉
    assert variants == ["原始问题", "v1", "v2", "v3"]


@pytest.mark.asyncio
async def test_generate_query_variants_falls_back_to_just_original_on_empty_response():
    mock_response = AsyncMock()
    mock_response.content = "   \n\n  "  # LLM 空回复/只有空白行

    with patch("app.agent.llm.get_llm") as mock_get_llm:
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_get_llm.return_value = mock_llm
        variants = await generate_query_variants("原始问题")

    assert variants == ["原始问题"]


# ---------------------------------------------------------------------------
# rag_fusion_search（整条编排：变体生成 → 并发检索 → RRF → 截断）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rag_fusion_search_merges_variant_results_via_rrf():
    fake_results = {
        "原始问题": ([{"id": "x", "score": 0.9}, {"id": "y", "score": 0.5}], 0.9),
        "变体一": ([{"id": "y", "score": 0.85}], 0.85),
        "变体二": ([{"id": "z", "score": 0.7}], 0.7),
    }

    async def fake_rag_search(query, top_k=3):
        return fake_results.get(query, ([], 0.0))

    with (
        patch("app.agent.rag.generate_query_variants", new=AsyncMock(return_value=["原始问题", "变体一", "变体二"])),
        patch("app.agent.rag.rag_search", new=AsyncMock(side_effect=fake_rag_search)) as mock_search,
    ):
        fused, top_score = await rag_fusion_search("原始问题", top_k=3)

    # y 在两个变体里都命中，融合后应该排第一；doc_map 保留最后一次出现（变体一）的分数
    assert [d["id"] for d in fused] == ["y", "x", "z"]
    assert top_score == 0.85
    assert mock_search.call_count == 3  # 每个查询变体各查了一次，没漏也没重复


@pytest.mark.asyncio
async def test_rag_fusion_search_respects_top_k_truncation():
    async def fake_rag_search(query, top_k=3):
        return [{"id": f"{query}-{i}", "score": 1.0 - i * 0.1} for i in range(top_k)], 0.9

    with (
        patch("app.agent.rag.generate_query_variants", new=AsyncMock(return_value=["q"])),
        patch("app.agent.rag.rag_search", new=AsyncMock(side_effect=fake_rag_search)),
    ):
        fused, _ = await rag_fusion_search("q", top_k=2)

    assert len(fused) == 2


@pytest.mark.asyncio
async def test_rag_fusion_search_returns_empty_when_nothing_found():
    with (
        patch("app.agent.rag.generate_query_variants", new=AsyncMock(return_value=["q"])),
        patch("app.agent.rag.rag_search", new=AsyncMock(return_value=([], 0.0))),
    ):
        fused, top_score = await rag_fusion_search("q")

    assert fused == []
    assert top_score == 0.0
