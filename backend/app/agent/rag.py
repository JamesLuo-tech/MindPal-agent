"""RAG 知识库检索 + SerpAPI 实时搜索双路架构。

流程：
  1. 用 BGE-M3 计算查询向量，pgvector 余弦相似度检索本地知识库（支持
     multi-query），这一步是高召回、低精度的粗筛——cosine 分数高只说明
     "语义邻居"，不代表这条资料真的答得了用户的问题（embedding 容易把
     同一话题域的句子放得很近，比如问"SSRI 有哪些副作用"，检索到"SSRI
     是什么"这条 chunk，cosine 可能照样很高）。
  2. 若最高分 >= RAG_THRESHOLD，再用 grade_relevance() 让 LLM 判一遍这些
     候选是不是真的能拿来回答问题——两道关卡都过了才真正当作"查到了"。
  3. 否则（cosine 不够，或者够了但 relevance grader 认为答不了）走 SerpAPI
     实时搜索（结果缓存 24h 到 Redis）。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re

import numpy as np
from sentence_transformers import SentenceTransformer

import app.database as _db
from app.config import get_settings
from app.redis_client import get_redis

RAG_THRESHOLD = 0.75
# 单次检索分数低于这个值时，判定为"明显不沾边"，不值得再花一次改写 LLM
# 调用 + 3 次额外向量检索去争取召回率，直接走网络兜底；分数在这个值和
# RAG_THRESHOLD 之间，才是真正模糊、值得用 RAG Fusion 争取一下的区间。
RAG_FUSION_MIN_SCORE = 0.5
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


async def search_raw(query: str, engine: str = "baidu") -> list[dict]:
    """跟 web_search 一样调 SerpAPI、一样缓存 24h，但返回未格式化的
    organic_results 原始结构，不丢弃 link/date 这些字段——web_search 把结果
    拼成一段给聊天 LLM 读的字符串，格式化过程会把这些元数据丢掉，但知识库
    候选挖掘（kb_candidate_service）需要保留每条资料的原始出处，所以另开
    一个函数，不去改 web_search 本身，避免影响已经在跑的聊天检索路径。
    """
    settings = get_settings()
    if not settings.serpapi_key:
        return []

    redis = await get_redis()
    cache_key = f"search_raw:{engine}:{hashlib.md5(query.encode()).hexdigest()}"
    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)

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
    await redis.setex(cache_key, SEARCH_CACHE_TTL, json.dumps(organic))
    return organic


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
# Relevance grading —— cosine 分数高之后的第二道关卡
# ---------------------------------------------------------------------------

_RELEVANCE_GRADE_PROMPT = (
    "判断下面每条资料是否真的包含能回答用户问题的具体信息——不是「话题相关」，"
    "而是「看完这条资料能不能答出用户的问题」。拿不准就算不能，不要放宽标准。\n\n"
    "用户问题：{query}\n\n"
    "资料：\n{items_text}\n\n"
    "请逐条判断，格式如下（不要加多余解释）：\n"
    "1: 能 / 不能\n"
    "2: 能 / 不能"
)


def build_relevance_grade_prompt(query: str, results: list[dict]) -> str:
    """纯函数，方便不起 LLM 就测 prompt 拼接对不对。"""
    items_text = "\n\n".join(
        f"[{i + 1}] {r.get('title', '')}\n{r.get('content', '')}" for i, r in enumerate(results)
    )
    return _RELEVANCE_GRADE_PROMPT.format(query=query, items_text=items_text)


def parse_relevance_grades(content: str, n: int) -> list[bool]:
    """解析 LLM 逐条给出的"能/不能"。保守默认：解析不到、格式不对、缺行，
    一律当"不能"——这道检查的目的就是收紧准确性，不能因为解析失败就放宽
    成默认通过，那样跟没加这道检查没区别。"""
    grades = [False] * n
    for line in content.strip().split("\n"):
        m = re.match(r"^\s*(\d+)\s*[:：]\s*(能|不能)", line)
        if not m:
            continue
        idx = int(m.group(1)) - 1
        if 0 <= idx < n:
            grades[idx] = m.group(2) == "能"
    return grades


async def grade_relevance(query: str, results: list[dict]) -> list[dict]:
    """cosine 相似度衡量的是向量空间里的接近程度，只能筛出"高召回"的候选，
    不能保证"内容上真的能回答问题"——两者不是一回事。这一步用 LLM 对
    rag_search/rag_fusion_search 筛出的候选再判一遍"这条资料是否真的能
    拿来回答用户的问题"，过滤掉语义邻居但答不上的假阳性，只有通过这道
    关卡的结果才应该被当作"查到了"直接返回，而不是仅凭 cosine 分数。

    返回过滤后仍然被判定为"能回答"的结果，保持原有顺序（分数最高的仍在前面，
    如果它被判定为不相关就被剔除，不会拿去顶替）。
    """
    if not results:
        return []
    from app.agent.llm import get_llm

    prompt = build_relevance_grade_prompt(query, results)
    response = await get_llm().ainvoke(prompt)
    grades = parse_relevance_grades(response.content, len(results))
    return [r for r, ok in zip(results, grades) if ok]


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
