"""LangChain 工具定义：lookup（RAG+搜索双路）和 recall_memory（语义记忆检索）。"""
import logging
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

import app.database as _db
from app.agent.memory import search_memories
from app.agent.rag import (
    RAG_FUSION_MIN_SCORE,
    RAG_THRESHOLD,
    format_rag_results,
    log_lookup,
    rag_fusion_search,
    rag_search,
    web_search,
)

logger = logging.getLogger(__name__)


@tool
async def lookup(query: str) -> str:
    """当用户提到具体的、可能有实用信息可查的小事时调用此工具。
    如：失眠、饮食问题、药物副作用、如何告诉家人自己病了、某个心理学概念等。

    不要在用户只是想倾诉情绪时调用。只在用户明确希望知道"怎么办"时使用。

    查询词用口语化中文，例如"焦虑导致的失眠缓解"、"SSRI 副作用"。

    Args:
        query: 要查询的具体问题，中文口语化

    Returns:
        相关信息摘要（2-3 条），供你用朋友聊天的方式讲出来
    """
    # 先用最便宜的单次检索探路——大多数"明显能查到"或"明显不沾边"的问题，
    # 到这一步就能定案，不用再多付一次改写 LLM 调用 + 3 次额外向量检索的成本
    # （比如问跑步消耗多少卡路里这种跟心理健康知识库完全不沾边的问题，
    # 之前会白跑一整套 RAG Fusion 才判断出该 fallback，拖慢了响应）。
    results, top_score = await rag_search(query, top_k=3)

    if RAG_FUSION_MIN_SCORE <= top_score < RAG_THRESHOLD:
        # 分数落在模糊地带——不算查到，但也没明显到可以直接放弃，
        # 这时候才值得用 RAG Fusion 的改写+多路召回再争取一次。
        results, top_score = await rag_fusion_search(query, top_k=3)

    if top_score >= RAG_THRESHOLD:
        await log_lookup(
            query,
            source="rag",
            rag_top_score=top_score,
            hit_kb_id=str(results[0]["id"]) if results else None,
        )
        return format_rag_results(results)

    await log_lookup(query, source="web", rag_top_score=top_score)
    return await web_search(query)


@tool
async def recall_memory(query: str, config: RunnableConfig) -> str:
    """从用户的长期语义记忆中检索相关历史对话。
    当用户提到"上次"、"之前"、"我跟你说过"等涉及历史对话内容时调用。

    Args:
        query: 检索关键词，如"上次提到的工作压力"、"之前说的家庭矛盾"

    Returns:
        相关历史对话摘要
    """
    logger.info("[recall_memory] 触发 | query=%s", query)

    user_id_str = (config.get("configurable") or {}).get("user_id")
    if not user_id_str:
        logger.warning("[recall_memory] 缺少 user_id，跳过检索")
        return "无法获取用户身份，记忆检索跳过。"

    pool = _db._pool
    if pool is None:
        logger.error("[recall_memory] 数据库连接池未就绪")
        return "数据库未就绪，记忆检索跳过。"

    user_id = UUID(user_id_str)
    try:
        async with pool.acquire() as conn:
            result = await search_memories(user_id, query, conn)
        hit = "暂无" not in result
        logger.info("[recall_memory] 完成 | user=%s | 命中=%s", user_id_str[:8], hit)
        return result
    except Exception as e:
        logger.exception("[recall_memory] 检索失败 | user=%s | error=%s", user_id_str[:8], e)
        return "记忆检索出错，请稍后再试。"


TOOLS = [lookup, recall_memory]
