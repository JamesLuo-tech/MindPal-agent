"""三层记忆管理。

L1 - 短时记忆：Redis，最近 10 轮，TTL 24h
L2 - 结构化长时记忆：PostgreSQL，用户档案 + 关键事件
L3 - 向量语义记忆：pgvector，对话摘要向量检索
"""
from __future__ import annotations

import json
from uuid import UUID

import asyncpg
import redis.asyncio as aioredis

SHORT_TERM_MAX_TURNS = 10
SHORT_TERM_TTL = 86400  # 24h
_MAX_MESSAGES = SHORT_TERM_MAX_TURNS * 2  # user + assistant per turn


def _redis_key(user_id: UUID, session_id: str) -> str:
    return f"shortmem:{user_id}:{session_id}"


async def load_short_term(
    user_id: UUID,
    session_id: str,
    redis: aioredis.Redis,
) -> list[dict]:
    """从 Redis 加载最近对话轮次。"""
    key = _redis_key(user_id, session_id)
    raw_items = await redis.lrange(key, 0, -1)
    return [json.loads(item) for item in raw_items]


async def save_short_term(
    user_id: UUID,
    session_id: str,
    messages: list[dict],
    redis: aioredis.Redis,
) -> None:
    """保存对话轮次到 Redis，保留最近 N 轮。"""
    key = _redis_key(user_id, session_id)
    pipe = redis.pipeline()
    for msg in messages:
        pipe.rpush(key, json.dumps(msg, ensure_ascii=False))
    pipe.ltrim(key, -_MAX_MESSAGES, -1)
    pipe.expire(key, SHORT_TERM_TTL)
    await pipe.execute()


async def load_long_term(user_id: UUID, pool: asyncpg.Pool) -> str:
    """从 PostgreSQL 加载用户档案和关键事件，拼成 SystemPrompt 使用的文本。"""
    async with pool.acquire() as db:
        profile = await db.fetchrow(
            "SELECT nickname, age_range, diagnosis FROM user_profiles WHERE user_id = $1",
            user_id,
        )
        events = await db.fetch(
            """
            SELECT event_type, content, created_at
            FROM key_events
            WHERE user_id = $1
            ORDER BY importance DESC, created_at DESC
            LIMIT 10
            """,
            user_id,
        )

    if not profile and not events:
        return ""

    parts: list[str] = ["[用户档案]"]
    if profile:
        if profile["nickname"]:
            parts.append(f"昵称：{profile['nickname']}")
        if profile["age_range"]:
            parts.append(f"年龄段：{profile['age_range']}")
        if profile["diagnosis"]:
            parts.append(f"诊断/状况：{profile['diagnosis']}")

    if events:
        parts.append("\n[重要记录]")
        for ev in events:
            date_str = ev["created_at"].strftime("%Y-%m-%d") if ev["created_at"] else ""
            parts.append(f"- [{ev['event_type']}] {ev['content']} ({date_str})")

    return "\n".join(parts)


async def search_memories(
    user_id: UUID,
    query: str,
    db: asyncpg.Connection,
    top_k: int = 3,
) -> str:
    """用 BGE-M3 向量检索语义相关的历史对话摘要。"""
    from app.agent.rag import _encode

    vec = await _encode(query)
    rows = await db.fetch(
        """
        SELECT summary, created_at,
               1 - (embedding <=> $1::vector) AS similarity
        FROM memories
        WHERE user_id = $2
        ORDER BY embedding <=> $1::vector
        LIMIT $3
        """,
        vec,
        user_id,
        top_k,
    )

    if not rows:
        return "暂无相关历史记录。"

    lines = ["[历史记忆]"]
    for row in rows:
        date_str = row["created_at"].strftime("%Y-%m-%d") if row["created_at"] else ""
        lines.append(f"- ({date_str}) {row['summary']}")

    return "\n".join(lines)


async def save_memory(
    user_id: UUID,
    summary: str,
    pool: asyncpg.Pool,
) -> None:
    """将对话摘要向量化后存入 memories 表。"""
    from app.agent.rag import _encode

    vec = await _encode(summary)
    async with pool.acquire() as db:
        await db.execute(
            """
            INSERT INTO memories (user_id, summary, embedding)
            VALUES ($1, $2, $3)
            """,
            user_id,
            summary,
            vec,
        )
