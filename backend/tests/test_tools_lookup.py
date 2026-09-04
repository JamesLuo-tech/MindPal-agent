"""lookup 工具的编排测试：确认它现在走的是 RAG Fusion（而不是单查询 rag_search），
以及本地知识库命中/未命中两条分支各自的行为没有被接线过程改坏。"""
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.tools import lookup


@pytest.mark.asyncio
async def test_lookup_uses_rag_fusion_search_not_plain_rag_search():
    with (
        patch("app.agent.tools.rag_fusion_search", new=AsyncMock(return_value=([], 0.0))) as mock_fusion,
        patch("app.agent.tools.log_lookup", new=AsyncMock()),
        patch("app.agent.tools.web_search", new=AsyncMock(return_value="web result")),
    ):
        await lookup.ainvoke({"query": "焦虑失眠怎么办"})

    mock_fusion.assert_awaited_once_with("焦虑失眠怎么办", top_k=3)


@pytest.mark.asyncio
async def test_lookup_returns_kb_results_when_fusion_score_above_threshold():
    fused_results = [{"id": "kb-1", "title": "失眠", "content": "……", "source": "丁香医生"}]

    with (
        patch("app.agent.tools.rag_fusion_search", new=AsyncMock(return_value=(fused_results, 0.9))),
        patch("app.agent.tools.log_lookup", new=AsyncMock()) as mock_log,
        patch("app.agent.tools.web_search", new=AsyncMock()) as mock_web,
    ):
        result = await lookup.ainvoke({"query": "失眠怎么办"})

    assert "失眠" in result
    mock_web.assert_not_awaited()  # 命中本地知识库就不该再打网络搜索
    mock_log.assert_awaited_once_with(
        "失眠怎么办", source="rag", rag_top_score=0.9, hit_kb_id="kb-1",
    )


@pytest.mark.asyncio
async def test_lookup_falls_back_to_web_search_when_fusion_score_below_threshold():
    with (
        patch("app.agent.tools.rag_fusion_search", new=AsyncMock(return_value=([], 0.2))),
        patch("app.agent.tools.log_lookup", new=AsyncMock()) as mock_log,
        patch("app.agent.tools.web_search", new=AsyncMock(return_value="web result")) as mock_web,
    ):
        result = await lookup.ainvoke({"query": "冷门问题"})

    assert result == "web result"
    mock_web.assert_awaited_once_with("冷门问题")
    mock_log.assert_awaited_once_with("冷门问题", source="web", rag_top_score=0.2)
