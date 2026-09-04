"""RAG 知识库检索 + SerpAPI 实时搜索双路架构。

流程：
  1. 用 BGE-M3 计算查询向量
  2. pgvector 余弦相似度检索本地知识库（支持 multi-query）
  3. 若最高分 >= RAG_THRESHOLD，直接返回
  4. 否则走 SerpAPI 实时搜索（结果缓存 24h 到 Redis）
"""
from __future__ import annotations

import asyncio
import hashlib

import numpy as np
from sentence_transformers import SentenceTransformer

import app.database as _db
from app.config import get_settings
from app.redis_client import get_redis

RAG_THRESHOLD = 0.75
SEARCH_CACHE_TTL = 86400  # 24h

TRUSTED_DOMAINS = [
    "dxy.com", "dxy.cn",
    "haoxinqing.cn",
    "psy.sysu.edu.cn",
    "bjmu.edu.cn",
    "who.int",
    "mayoclinic.org",
    "psychiatry.org",
]

_embedder: SentenceTransformer | None = None


def _load_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer("BAAI/bge-m3")
    return _embedder


async def _encode(text: str) -> np.ndarray:
    """在线程池里运行 BGE-M3 编码，避免阻塞事件循环。"""
    loop = asyncio.get_running_loop()
    vec = await loop.run_in_executor(
        None,
        lambda: _load_embedder().encode(text, normalize_embeddings=True),
    )
    return vec


# ---------------------------------------------------------------------------
# 核心检索
# ---------------------------------------------------------------------------

async def rag_search(query: str, top_k: int = 3) -> tuple[list[dict], float]:
    """查本地知识库。返回 (结果列表, 最高相似度分数)。"""
    pool = _db._pool
    if pool is None:
        return [], 0.0

    vec = await _encode(query)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, content, source, source_url,
                   1 - (embedding <=> $1) AS score
            FROM knowledge_base
            WHERE is_active = TRUE
            ORDER BY embedding <=> $1
            LIMIT $2
            """,
            vec,
            top_k,
        )

    results = [dict(r) for r in rows]
    top_score = float(results[0]["score"]) if results else 0.0
    return results, top_score


async def web_search(query: str, engine: str = "baidu") -> str:
    """通过 SerpAPI 实时搜索，结果缓存到 Redis 24h。"""
    settings = get_settings()
    if not settings.serpapi_key:
        return "(SerpAPI 未配置，无法实时搜索)"

    redis = await get_redis()
    cache_key = f"search:{engine}:{hashlib.md5(query.encode()).hexdigest()}"
    cached = await redis.get(cache_key)
    if cached:
        return cached

    # SerpAPI SDK 是同步的，放到线程池里跑
    from serpapi import GoogleSearch

    params: dict = {
        "engine": engine,
        "q": query,
        "api_key": settings.serpapi_key,
        "num": 10,
    }
    if engine == "google":
        params["hl"] = "zh-cn"

    loop = asyncio.get_running_loop()
    raw = await loop.run_in_executor(
        None, lambda: GoogleSearch(params).get_dict()
    )

    organic: list[dict] = raw.get("organic_results", [])
    # 可信来源排前面
    organic.sort(
        key=lambda r: (
            0 if any(d in r.get("link", "") for d in TRUSTED_DOMAINS) else 1,
            r.get("position", 99),
        )
    )

    result = format_serp_results(organic[:3], answer_box=raw.get("answer_box"))
    await redis.setex(cache_key, SEARCH_CACHE_TTL, result)
    return result


# ---------------------------------------------------------------------------
# 格式化（供 LLM 消化）
# ---------------------------------------------------------------------------

def format_rag_results(results: list[dict]) -> str:
    lines = ["(来自本地知识库，请用朋友聊天的方式带入回应，不要念条目)\n"]
    for i, r in enumerate(results[:2], 1):
        lines.append(f"[{i}] 关于「{r['title']}」")
        lines.append(f"    {r['content']}")
        if r.get("source"):
            lines.append(f"    来源: {r['source']}")
        lines.append("")
    return "\n".join(lines)


def format_serp_results(results: list, answer_box: dict | None = None) -> str:
    lines = ["(来自实时搜索，请用朋友聊天的方式讲，不要念条目)\n"]

    if answer_box and answer_box.get("snippet"):
        lines.append(f"[精选摘要] {answer_box['snippet']}")
        lines.append("")

    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        snippet = (r.get("snippet") or "")[:300]
        source = r.get("displayed_link", "")
        lines.append(f"[{i}] {title}")
        if snippet:
            lines.append(f"    {snippet}")
        lines.append(f"    来源: {source}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Multi-query 检索
# ---------------------------------------------------------------------------

async def generate_query_variants(query: str) -> list[str]:
    """用 LLM 将原始查询改写成多种表达，提高召回率。"""
    from app.agent.llm import get_llm
    prompt = (
        "请将以下问题改写成3种不同的表达方式，用于检索心理健康知识库。\n"
        "每种改写单独一行，不要加编号或标点前缀。\n\n"
        f"原始问题：{query}\n\n3种改写："
    )
    response = await get_llm().ainvoke(prompt)
    variants = [q.strip() for q in response.content.strip().split("\n") if q.strip()]
    return [query] + variants[:3]


def _reciprocal_rank_fusion(results_list: list[list[dict]], k: int = 60) -> list[dict]:
    """RRF 重排：对多组检索结果按排名综合打分，排名越靠前分越高。"""
    rrf_scores: dict[str, float] = {}
    doc_map: dict[str, dict] = {}

    for results in results_list:
        for rank, doc in enumerate(results):
            doc_id = str(doc["id"])
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
            doc_map[doc_id] = doc

    sorted_ids = sorted(rrf_scores, key=lambda x: rrf_scores[x], reverse=True)
    return [doc_map[i] for i in sorted_ids]


async def rag_fusion_search(query: str, top_k: int = 3) -> tuple[list[dict], float]:
    """RAG Fusion：生成查询变体 → 各自并发检索 → RRF 重排 → 返回最优结果。

    并发发起各变体的检索（互相独立的只读查询），避免叠加成 4 次串行往返——
    这条路径现在挂在实时聊天的 lookup 工具上，比原来只在离线评测脚本里跑
    多了延迟敏感这一层考虑。
    """
    variants = await generate_query_variants(query)

    results_list = await asyncio.gather(
        *(rag_search(q, top_k=top_k) for q in variants)
    )
    results_list = [results for results, _ in results_list]

    fused = _reciprocal_rank_fusion(results_list)
    top_score = float(fused[0]["score"]) if fused else 0.0
    return fused[:top_k], top_score


# ---------------------------------------------------------------------------
# 查询日志
# ---------------------------------------------------------------------------

async def log_lookup(
    query: str,
    source: str,
    rag_top_score: float | None = None,
    hit_kb_id: str | None = None,
) -> None:
    """写入 lookup_logs，供后续 RAG 迭代分析。失败静默，不影响主流程。"""
    pool = _db._pool
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO lookup_logs (query, source, rag_top_score, hit_kb_id)
                VALUES ($1, $2, $3, $4)
                """,
                query,
                source,
                rag_top_score,
                hit_kb_id,
            )
    except Exception:
        pass  # 日志失败不能影响主流程
