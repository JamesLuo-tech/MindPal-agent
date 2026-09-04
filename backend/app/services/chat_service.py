"""对话服务层：协调 Agent、记忆、危机检测、持久化的完整流程。"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator
from uuid import UUID, uuid4

import redis.asyncio as aioredis
from langchain_core.messages import AIMessage, HumanMessage

import app.database as _db
from app.agent.actions import ACTION_TOOL_NAMES
from app.agent.crisis import CRITICAL_KEYWORDS, HOTLINE_APPEND, check_and_append_hotline
from app.agent.emotion import extract_emotion, save_emotion
from app.agent.graph import get_graph
from app.agent.llm import get_llm
from app.agent.memory import (
    load_long_term,
    load_safety_plan,
    load_short_term,
    save_memory,
    save_short_term,
)

RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = 30
MEMORY_SAVE_INTERVAL = 5


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# 哪些节点的 LLM 输出流该转发给前端。router 自己的分类调用、run_segment 里
# 每一段单独的（未经合并的）回答都不该被用户看到——多意图场景下，只有 merge
# 合成后的最终文字才是真正的回复。单意图场景完全不受影响：那时 merge 只是
# 纯透传，不会调 LLM，也就不会产生这类事件。
_STREAMABLE_NODES = frozenset({"empathy", "knowledge", "action", "merge"})


def should_forward_chat_stream(node_name: str | None) -> bool:
    """判断某个 on_chat_model_stream 事件要不要转发给前端。

    单独抽成纯函数，好在不用起 graph/DB/Redis 的情况下测试这条过滤规则——
    尤其是多意图路径下"中间分支不该被转发、只有合并结果该被转发"这条约束。
    """
    return node_name in _STREAMABLE_NODES


def parse_action_proposal(tool_name: str, output: object) -> dict | None:
    """把某个 propose_* 工具的原始输出解析成 {action, params, summary}；
    不是 action 工具、或者解析失败（不该发生，但防御一下）时返回 None。

    单独抽成纯函数，好在不用起 graph/DB/Redis 的情况下测试这段解析逻辑。
    """
    if tool_name not in ACTION_TOOL_NAMES:
        return None

    raw = getattr(output, "content", None)
    if raw is None:
        raw = str(output) if output is not None else ""

    try:
        proposal = json.loads(raw)
        return {
            "action": proposal["action"],
            "params": proposal["params"],
            "summary": proposal["summary"],
        }
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"[WARN] 解析 action 提议失败: {e} | raw={raw!r}")
        return None


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

    # 命中危机关键词时，把用户自己写过的安全计划一并给 Agent 参考，
    # 让回应能落到"你安全计划里写的那个方法，要不要现在试试"这种具体程度，
    # 而不是每轮对话都带上（避免闲聊时被突兀地提起）
    if any(kw in user_message for kw in CRITICAL_KEYWORDS):
        try:
            safety_plan_text = await load_safety_plan(user_id, pool)
            if safety_plan_text:
                long_term = f"{long_term}\n\n{safety_plan_text}" if long_term else safety_plan_text
        except Exception as e:
            print(f"[WARN] 加载安全计划失败: {e}")

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
                node_name = event.get("metadata", {}).get("langgraph_node")
                if not should_forward_chat_stream(node_name):
                    continue
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
                tool_name = event["name"]
                yield _sse("tool_result", {"tool": tool_name, "status": "done"})

                # propose_* 工具只生成了一条待确认的提议，转成 action_proposal 事件
                # 推给前端弹确认卡片——真正的数据库写入要等用户点确认后另外调接口。
                proposal = parse_action_proposal(tool_name, event["data"].get("output"))
                if proposal:
                    yield _sse("action_proposal", {"proposal_id": str(uuid4()), **proposal})

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
            used_tools,
        )
    return ai_message_id
