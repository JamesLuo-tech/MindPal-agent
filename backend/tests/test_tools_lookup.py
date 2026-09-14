"""lookup 工具的编排测试：先单次检索探路，只有分数落在"模糊地带"
（RAG_FUSION_MIN_SCORE ~ RAG_THRESHOLD 之间）才升级到 RAG Fusion，
明显能查到或明显查不到的情况都不该多付一次改写 LLM 调用的成本。

cosine 分数达标之后还有一道 relevance grader 关卡（见文件末尾 grading
相关测试）——下面"分数够高就直接返回"的测试都要把 grade_relevance mock
成"全部判定为相关"，因为现在光 cosine 分数够高不能直接返回了，得两道
关卡（retrieval score + relevance score）都过。
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.tools import lookup


@pytest.mark.asyncio
async def test_lookup_skips_fusion_when_single_query_score_already_high():
    """单次检索已经明显命中（>= RAG_THRESHOLD）时，不该再多跑一次 Fusion。"""
    kb_results = [{"id": "kb-1", "title": "失眠", "content": "……", "source": "丁香医生"}]

    with (
        patch("app.agent.tools.rag_search", new=AsyncMock(return_value=(kb_results, 0.9))),
        patch("app.agent.tools.rag_fusion_search", new=AsyncMock()) as mock_fusion,
        patch("app.agent.tools.grade_relevance", new=AsyncMock(return_value=kb_results)),
        patch("app.agent.tools.log_lookup", new=AsyncMock()) as mock_log,
        patch("app.agent.tools.web_search", new=AsyncMock()) as mock_web,
    ):
        result = await lookup.ainvoke({"query": "失眠怎么办"})

    assert "失眠" in result
    mock_fusion.assert_not_awaited()  # 单次检索已经够好，不该多花一次 Fusion 的成本
    mock_web.assert_not_awaited()
    mock_log.assert_awaited_once_with(
        "失眠怎么办", source="rag", rag_top_score=0.9, hit_kb_id="kb-1",
    )


@pytest.mark.asyncio
async def test_lookup_skips_fusion_when_single_query_score_clearly_low():
    """单次检索分数明显很低（< RAG_FUSION_MIN_SCORE）时，判定为明显不沾边，
    直接走网络兜底，不该为了拉召回率再跑一次 Fusion——这是修复"跑步消耗
    多少卡路里"这类完全跑题问题响应慢的关键：不用再付改写 LLM 调用的代价。"""
    with (
        patch("app.agent.tools.rag_search", new=AsyncMock(return_value=([], 0.2))),
        patch("app.agent.tools.rag_fusion_search", new=AsyncMock()) as mock_fusion,
        patch("app.agent.tools.grade_relevance", new=AsyncMock()) as mock_grade,
        patch("app.agent.tools.log_lookup", new=AsyncMock()) as mock_log,
        patch("app.agent.tools.web_search", new=AsyncMock(return_value="web result")) as mock_web,
    ):
        result = await lookup.ainvoke({"query": "跑步半小时消耗多少卡路里"})

    assert result == "web result"
    mock_fusion.assert_not_awaited()
    mock_grade.assert_not_awaited()  # 分数没达标，不该跑相关性判分
    mock_web.assert_awaited_once_with("跑步半小时消耗多少卡路里")
    mock_log.assert_awaited_once_with("跑步半小时消耗多少卡路里", source="web", rag_top_score=0.2)


@pytest.mark.asyncio
async def test_lookup_escalates_to_fusion_when_score_in_ambiguous_zone():
    """单次检索分数落在模糊地带（RAG_FUSION_MIN_SCORE 到 RAG_THRESHOLD 之间）时，
    才值得用 RAG Fusion 的改写+多路召回再争取一次，最终结果以 Fusion 的为准。"""
    fused_results = [{"id": "kb-2", "title": "焦虑", "content": "……", "source": "临床心理整理"}]

    with (
        patch("app.agent.tools.rag_search", new=AsyncMock(return_value=([], 0.6))),
        patch("app.agent.tools.rag_fusion_search", new=AsyncMock(return_value=(fused_results, 0.85))) as mock_fusion,
        patch("app.agent.tools.grade_relevance", new=AsyncMock(return_value=fused_results)),
        patch("app.agent.tools.log_lookup", new=AsyncMock()) as mock_log,
        patch("app.agent.tools.web_search", new=AsyncMock()) as mock_web,
    ):
        result = await lookup.ainvoke({"query": "情绪不太稳定该怎么办"})

    mock_fusion.assert_awaited_once_with("情绪不太稳定该怎么办", top_k=3)
    assert "焦虑" in result
    mock_web.assert_not_awaited()
    mock_log.assert_awaited_once_with(
        "情绪不太稳定该怎么办", source="rag", rag_top_score=0.85, hit_kb_id="kb-2",
    )


@pytest.mark.asyncio
async def test_lookup_falls_back_to_web_when_fusion_still_below_threshold():
    """升级到 Fusion 之后分数还是不够，最终还是要 fallback 到网络搜索。"""
    with (
        patch("app.agent.tools.rag_search", new=AsyncMock(return_value=([], 0.6))),
        patch("app.agent.tools.rag_fusion_search", new=AsyncMock(return_value=([], 0.65))) as mock_fusion,
        patch("app.agent.tools.grade_relevance", new=AsyncMock()) as mock_grade,
        patch("app.agent.tools.log_lookup", new=AsyncMock()) as mock_log,
        patch("app.agent.tools.web_search", new=AsyncMock(return_value="web result")) as mock_web,
    ):
        result = await lookup.ainvoke({"query": "情绪不太稳定该怎么办"})

    mock_fusion.assert_awaited_once()
    assert result == "web result"
    mock_grade.assert_not_awaited()  # 分数还是没达标，不该跑相关性判分
    mock_web.assert_awaited_once_with("情绪不太稳定该怎么办")
    mock_log.assert_awaited_once_with("情绪不太稳定该怎么办", source="web", rag_top_score=0.65)


@pytest.mark.asyncio
async def test_lookup_boundary_score_exactly_at_fusion_min_escalates():
    """边界值：分数正好等于 RAG_FUSION_MIN_SCORE 时应该按"模糊地带"处理（左闭），
    不应该被当成"明显不沾边"直接跳过 Fusion。"""
    with (
        patch("app.agent.tools.rag_search", new=AsyncMock(return_value=([], 0.5))),
        patch("app.agent.tools.rag_fusion_search", new=AsyncMock(return_value=([], 0.5))) as mock_fusion,
        patch("app.agent.tools.log_lookup", new=AsyncMock()),
        patch("app.agent.tools.web_search", new=AsyncMock(return_value="web result")),
    ):
        await lookup.ainvoke({"query": "边界值测试"})

    mock_fusion.assert_awaited_once()


# ---------------------------------------------------------------------------
# relevance grading —— cosine 分数达标之后的第二道关卡
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lookup_falls_back_to_web_when_cosine_high_but_grader_rejects_all():
    """核心场景：cosine 分数很高，但 relevance grader 判定这些候选都答不了
    用户的问题（语义邻居但不是真答案）——不能只凭 cosine 分数就直接返回，
    得转去网络兜底，而且日志里要如实记录原始的 cosine 分数（不能因为被
    grader 拒绝就抹掉，这个信号对后续分析检索质量有用）。"""
    kb_results = [{"id": "kb-1", "title": "SSRI 是什么", "content": "……", "source": "丁香医生"}]

    with (
        patch("app.agent.tools.rag_search", new=AsyncMock(return_value=(kb_results, 0.92))),
        patch("app.agent.tools.rag_fusion_search", new=AsyncMock()) as mock_fusion,
        patch("app.agent.tools.grade_relevance", new=AsyncMock(return_value=[])) as mock_grade,
        patch("app.agent.tools.log_lookup", new=AsyncMock()) as mock_log,
        patch("app.agent.tools.web_search", new=AsyncMock(return_value="web result")) as mock_web,
    ):
        result = await lookup.ainvoke({"query": "SSRI 有哪些副作用"})

    mock_fusion.assert_not_awaited()
    mock_grade.assert_awaited_once_with("SSRI 有哪些副作用", kb_results)
    assert result == "web result"
    mock_web.assert_awaited_once_with("SSRI 有哪些副作用")
    # 原始 cosine 分数（0.92）要如实记进日志，不能因为被 grader 拒绝就清零
    mock_log.assert_awaited_once_with("SSRI 有哪些副作用", source="web", rag_top_score=0.92)


@pytest.mark.asyncio
async def test_lookup_returns_only_the_results_grader_confirms_as_relevant():
    """grader 可能只认可候选里的一部分——最终返回的应该是过滤后的子集，
    不是原始的全部候选。"""
    kb_results = [
        {"id": "kb-1", "title": "真正相关", "content": "答案在这里", "source": "丁香医生"},
        {"id": "kb-2", "title": "语义邻居但答不了", "content": "跑题内容", "source": "丁香医生"},
    ]
    relevant_only = [kb_results[0]]

    with (
        patch("app.agent.tools.rag_search", new=AsyncMock(return_value=(kb_results, 0.9))),
        patch("app.agent.tools.rag_fusion_search", new=AsyncMock()),
        patch("app.agent.tools.grade_relevance", new=AsyncMock(return_value=relevant_only)),
        patch("app.agent.tools.log_lookup", new=AsyncMock()) as mock_log,
        patch("app.agent.tools.web_search", new=AsyncMock()) as mock_web,
    ):
        result = await lookup.ainvoke({"query": "问题"})

    assert "真正相关" in result
    assert "语义邻居但答不了" not in result
    mock_web.assert_not_awaited()
    mock_log.assert_awaited_once_with(
        "问题", source="rag", rag_top_score=0.9, hit_kb_id="kb-1",
    )
