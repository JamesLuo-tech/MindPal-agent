"""从 lookup_logs 里挖"本地知识库没覆盖到、但被真实问过"的话题，用搜索到的
真实资料起草候选知识库词条，供人工审核后再决定要不要真的收进
knowledge_base——跟 propose_* 写入工具同一套"提议-确认"安全模型：LLM
生成的内容在人工把 approved 改成 true 之前，不会进真正的知识库。
"""
from __future__ import annotations

import asyncpg

_KB_DRAFT_PROMPT = (
    "你在帮一个心理健康知识库整理一条新词条。下面是搜索引擎针对某个用户问题"
    "返回的真实资料，请只根据这些资料整理出一条结构清晰、口语化的知识条目，"
    "不要编造资料里没有的内容，也不要原样照抄——用自己的话组织成 2-4 段小短文，"
    "风格参考：用朋友聊天的口吻讲清楚是什么、怎么做，必要时提醒什么情况要就医。\n\n"
    "用户问题：{query}\n\n"
    "搜索到的资料：\n{material}\n\n"
    "请按下面的格式输出（不要加多余的解释）：\n"
    "标题: <一句话概括这个问题>\n"
    "正文: <2-4 段整理好的内容>"
)


def group_uncovered_queries(rows: list[dict], min_count: int = 1) -> list[dict]:
    """把 lookup_logs 里 source='web' 的记录按问题原文（去首尾空格、忽略大小写）
    聚合，返回出现次数 >= min_count 的分组，按次数从高到低排序。

    纯函数，不连数据库，好测。注意这只是精确字符串匹配，同一个意图换种
    说法问不会被聚到一起（比如"失眠怎么办"和"睡不着怎么办"会被当成两条）——
    真要做语义聚类需要再接一次 embedding 相似度分组，但现在 lookup_logs
    里数据还很少，没必要为了几条数据先上更复杂的聚类逻辑，先把"有没有
    这条流水线"这件事做出来，数据量上来了再考虑要不要精细化分组。
    """
    groups: dict[str, dict] = {}
    for row in rows:
        key = row["query"].strip().lower()
        if not key:
            continue
        if key not in groups:
            groups[key] = {"query_text": row["query"].strip(), "count": 0, "log_ids": []}
        groups[key]["count"] += 1
        groups[key]["log_ids"].append(str(row["id"]))

    result = [g for g in groups.values() if g["count"] >= min_count]
    result.sort(key=lambda g: g["count"], reverse=True)
    return result


def build_kb_draft_prompt(query: str, material: str) -> str:
    """纯函数，方便不起 LLM 就测 prompt 拼接对不对。"""
    return _KB_DRAFT_PROMPT.format(query=query, material=material)


def parse_kb_draft_response(content: str) -> dict | None:
    """解析 LLM 起草的候选词条，拆出标题和正文。格式不对就返回 None，
    调用方应该跳过这条留给人工直接手写，而不是硬凑一条格式错误的候选。
    """
    lines = content.strip().split("\n")
    title = None
    body_lines: list[str] = []
    in_body = False
    for line in lines:
        if line.startswith("标题:") or line.startswith("标题："):
            title = line.split(":", 1)[-1].split("：", 1)[-1].strip()
        elif line.startswith("正文:") or line.startswith("正文："):
            in_body = True
            rest = line.split(":", 1)[-1].split("：", 1)[-1].strip()
            if rest:
                body_lines.append(rest)
        elif in_body:
            body_lines.append(line)

    body = "\n".join(body_lines).strip()
    if not title or not body:
        return None
    return {"title": title, "content": body}


async def fetch_uncovered_queries(pool: asyncpg.Pool, since=None) -> list[dict]:
    """查 lookup_logs 里所有走了网络兜底的记录（本地知识库没覆盖到的问题）。"""
    query = "SELECT id, query, created_at FROM lookup_logs WHERE source = 'web'"
    params: list = []
    if since is not None:
        query += " AND created_at >= $1"
        params.append(since)
    query += " ORDER BY created_at DESC"

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
    return [dict(r) for r in rows]


async def insert_approved_candidate(
    pool: asyncpg.Pool,
    topic: str,
    title: str,
    content: str,
    source: str,
    quality_score: float = 0.8,
) -> str:
    """人工确认过的候选词条，真正写进 knowledge_base——只有这一步执行完，
    内容才会被检索到。quality_score 默认给 0.8，比种子文档的 0.9+ 略低，
    标记这是自动挖掘 + 人工审核的内容，不是最初精心整理的那批种子数据。
    """
    from app.agent.rag import _encode

    vec = await _encode(f"{title}\n\n{content}")
    async with pool.acquire() as conn:
        row_id = await conn.fetchval(
            """
            INSERT INTO knowledge_base (topic, title, content, source, embedding, quality_score)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            topic, title, content, source, vec, quality_score,
        )
    return str(row_id)
