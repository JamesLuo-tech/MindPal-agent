"""对话服务层：协调 Agent、记忆、危机检测、持久化的完整流程。"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator
from uuid import UUID

import redis.asyncio as aioredis
from langchain_core.messages import AIMessage, HumanMessage

import app.database as _db
from app.agent.crisis import HOTLINE_APPEND, check_and_append_hotline
from app.agent.emotion import extract_emotion, save_emotion
from app.agent.graph import get_graph
from app.agent.llm import get_llm
from app.agent.memory import (
    load_long_term,
    load_short_term,
    save_memory,
    save_short_term,
)

RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = 30
MEMORY_SAVE_INTERVAL = 5


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _check_rate_limit(user_id: UUID, redis: aioredis.Redis) -> bool:
    key = f"ratelimit:{user_id}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, RATE_LIMIT_WINDOW)
    return count <= RATE_LIMIT_MAX


async def stream_chat(
    user_id: UUID,
    conversation_id: UUID,
    user_message: str,
    redis: aioredis.Redis,
) -> AsyncGenerator[str, None]:
    """主对话流程，yield SSE 格式字符串。

    每个 DB 操作都在独立的 pool.acquire() 块中完成，
    不跨越任何 yield 点持有连接，避免 asyncpg 在生成器暂停时
    将连接释放回连接池的问题。
    """
    # [1] 限流
    if not await _check_rate_limit(user_id, redis):
        yield _sse("error", {"code": "rate_limited", "message": "消息太频繁，请稍等一下"})
        return

    pool = _db._pool
    if pool is None:
        yield _sse("error", {"code": "db_error", "message": "数据库未初始化"})
        return

    # [2] 加载记忆（独立连接，不跨越 yield）
    session_id = str(conversation_id)
    short_term = await load_short_term(user_id, session_id, redis)
    try:
        long_term = await load_long_term(user_id, pool)
    except Exception as e:
        print(f"[WARN] 加载长时记忆失败: {e}")
        long_term = ""

    # [3] 重建历史消息列表
    history: list = []
    for m in short_term:
        if m["role"] == "user":
            history.append(HumanMessage(content=m["content"]))
        else:
            history.append(AIMessage(content=m["content"]))

    graph_input = {
        "messages": history + [HumanMessage(content=user_message)],
        "user_id": str(user_id),
        "conversation_id": str(conversation_id),
        "long_term_memory": long_term,
        "crisis_triggered": False,
        "agent_type": "",
    }
    graph_config = {"configurable": {"user_id": str(user_id)}}

    # [4] LangGraph 流式推理（此段跨越多个 yield，不持有 DB 连接）
    graph = await get_graph()
    full_response = ""
    used_tools: list[str] = []

    try:
        async for event in graph.astream_events(graph_input, config=graph_config, version="v2"):
            kind = event["event"]

            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if chunk.content:
                    full_response += chunk.content
                    yield _sse("message", {"delta": chunk.content})

            elif kind == "on_tool_start":
                tool_name = event["name"]
                tool_input = event["data"].get("input", {})
                used_tools.append(tool_name)
                yield _sse("tool_use", {
                    "tool": tool_name,
                    "query": tool_input.get("query", ""),
                    "status": "searching",
                })

            elif kind == "on_tool_end":
                yield _sse("tool_result", {"tool": event["name"], "status": "done"})

    except Exception as e:
        yield _sse("error", {"code": "agent_error", "message": str(e)})
        return

    # [5] 危机检测
    final_response, crisis_triggered = check_and_append_hotline(user_message, full_response)
    if crisis_triggered:
        yield _sse("message", {"delta": HOTLINE_APPEND})

    # [6] 持久化消息（独立连接）
    message_id = None
    try:
        message_id = await _save_messages(
            pool, user_id, conversation_id, user_message, final_response, used_tools
        )
    except Exception as e:
        print(f"[WARN] 保存消息失败: {e}")

    # [7] 更新短时记忆
    try:
        await save_short_term(
            user_id, session_id,
            [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": final_response},
            ],
            redis,
        )
    except Exception as e:
        print(f"[WARN] 更新短时记忆失败: {e}")

    # [8] 向量记忆（独立连接）
    try:
        turn_count = len(short_term) // 2 + 1
        if turn_count % MEMORY_SAVE_INTERVAL == 0:
            summary = f"用户：{user_message[:120]}\nMindPal：{final_response[:240]}"
            await save_memory(user_id, summary, pool)
    except Exception as e:
        print(f"[WARN] 保存向量记忆失败: {e}")

    # [9] 情绪提取（后台）
    if message_id:
        asyncio.create_task(
            _emotion_background(user_id, message_id, user_message, full_response)
        )

    # [10] 完成
    yield _sse("done", {
        "message_id": str(message_id) if message_id else "",
        "crisis_triggered": crisis_triggered,
    })


async def _emotion_background(
    user_id: UUID,
    message_id: UUID,
    user_message: str,
    ai_response: str,
) -> None:
    pool = _db._pool
    if pool is None:
        return
    try:
        emotion = await extract_emotion(user_message, ai_response, get_llm())
        async with pool.acquire() as conn:
            await save_emotion(user_id, message_id, emotion, conn)
    except Exception:
        pass


async def _save_messages(
    pool,
    user_id: UUID,
    conversation_id: UUID,
    user_message: str,
    ai_response: str,
    used_tools: list[str],
) -> UUID:
    async with pool.acquire() as db:
        owner = await db.fetchval(
            "SELECT user_id FROM conversations WHERE id = $1",
            conversation_id,
        )
        if str(owner) != str(user_id):
            raise PermissionError("conversation not owned by user")

        await db.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES ($1, $2, $3)",
            conversation_id, "user", user_message,
        )

        ai_message_id = await db.fetchval(
            """
            INSERT INTO messages (conversation_id, role, content, used_tools)
            VALUES ($1, $2, $3, $4::jsonb)
            RETURNING id
            """,
            conversation_id, "assistant", ai_response,
            json.dumps(used_tools, ensure_ascii=False),
        )
    return ai_message_id
