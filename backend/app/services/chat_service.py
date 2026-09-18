"""对话服务层：协调 Agent、记忆、危机检测、持久化的完整流程。"""
from __future__ import annotations

import asyncio
import contextlib
import json
from typing import AsyncGenerator
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import Request
from langchain_core.messages import AIMessage, HumanMessage

import app.database as _db
from app.agent.actions import ACTION_TOOL_NAMES
from app.agent.crisis import (
    HOTLINE_APPEND,
    append_hotline_if_triggered,
    assess_crisis,
    save_crisis_event,
)
from app.agent.emotion import extract_emotion, save_emotion
from app.agent.graph import get_graph
from app.agent.llm import get_llm
from app.agent.memory import (
    increment_turn_count,
    load_long_term,
    load_reflection_note,
    load_safety_plan,
    load_short_term,
    save_memory,
    save_reflection_note,
    save_short_term,
)
from app.agent.profile_extraction import extract_profile_info, save_key_event, save_profile_updates
from app.agent.reflection import reflect_on_turn
from app.services.action_proposal_service import create_proposal

RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = 30
MEMORY_SAVE_INTERVAL = 5
# 轮询 request.is_disconnected() 的间隔——不用数据库连接池的状态判断客户端
# 是否还在（连接池跟 HTTP 连接是两回事，池子健康不代表这个具体请求的
# 客户端还连着），直接问 FastAPI 的 Request 对象最准确、也是官方推荐的做法。
DISCONNECT_POLL_INTERVAL = 0.5


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


async def _watch_disconnect(request: Request, gen_task: asyncio.Task) -> None:
    """轮询 request.is_disconnected()；一旦客户端断开（真的断网，或者前端
    AbortController 主动停止生成——这两种在服务端看来是同一件事），直接
    cancel 掉 gen_task。

    只需要 cancel 这一个 task：gen_task 内部是 `async for event in
    graph.astream_events(...)`，取消这一个 Task 会被 asyncio 自动级联传播
    到它当前正在 await 的所有子调用——不管此刻卡在 pgvector 检索、
    run_in_executor 里跑的 SerpAPI 调用，还是 LLM 的流式请求，都不用
    分别给 retrieval/SerpAPI/LLM 各起一个 task handle 手动去 cancel。

    gen_task 自然跑完时这个循环也会自己退出，不依赖外面显式 cancel 它。
    """
    try:
        while not gen_task.done():
            try:
                if await request.is_disconnected():
                    gen_task.cancel()
                    return
            except Exception as e:
                # is_disconnected() 本身出错是极少见的情况——保守起见当成
                # "还连着"处理，不能因为探测本身出错就误杀正常请求。
                print(f"[WARN] 检测客户端连接状态失败: {e}")
            await asyncio.sleep(DISCONNECT_POLL_INTERVAL)
    except asyncio.CancelledError:
        pass


async def _run_graph_events(
    graph,
    graph_input: dict,
    graph_config: dict,
    pool,
    user_id: UUID,
    conversation_id: UUID,
    queue: "asyncio.Queue[str | None]",
    result: dict,
) -> None:
    """真正跑 LangGraph 流式推理的任务体——retrieval（lookup 工具里的
    pgvector 检索）、SerpAPI 实时搜索、LLM 生成全部发生在这个任务的调用链
    里，整个函数会被包成一个独立的 asyncio.Task，好让 _watch_disconnect
    能整体 cancel 掉它（见上面的说明）。

    这里没法像原来那样直接 yield SSE 字符串给调用方（Task 没有"边跑边
    yield"给外部生成器的机制），所以改成往 queue 里 put；处理到的
    full_response/used_tools/segment_drafts 通过外面传进来的 result 字典
    原地更新带出去。跑完（不管正常结束、内部出错、还是被 cancel）最后都
    会往 queue 里放一个 None 当结束哨兵，让外层消费循环知道该收尾了。
    """
    try:
        async for event in graph.astream_events(graph_input, config=graph_config, version="v2"):
            kind = event["event"]

            if kind == "on_chat_model_stream":
                node_name = event.get("metadata", {}).get("langgraph_node")
                if not should_forward_chat_stream(node_name):
                    continue
                chunk = event["data"]["chunk"]
                if chunk.content:
                    result["full_response"] += chunk.content
                    await queue.put(_sse("message", {"delta": chunk.content}))

            elif kind == "on_chain_start" and event.get("name") == "merge":
                drafts = event["data"].get("input", {}).get("segment_responses")
                if drafts and len(drafts) > 1:
                    result["segment_drafts"] = drafts

            elif kind == "on_tool_start":
                tool_name = event["name"]
                tool_input = event["data"].get("input", {})
                result["used_tools"].append(tool_name)
                await queue.put(_sse("tool_use", {
                    "tool": tool_name,
                    "query": tool_input.get("query", ""),
                    "status": "searching",
                }))

            elif kind == "on_tool_end":
                tool_name = event["name"]
                await queue.put(_sse("tool_result", {"tool": tool_name, "status": "done"}))

                proposal = parse_action_proposal(tool_name, event["data"].get("output"))
                if proposal:
                    try:
                        async with pool.acquire() as db:
                            created = await create_proposal(
                                user_id, conversation_id,
                                proposal["action"], proposal["params"], proposal["summary"],
                                db,
                            )
                        await queue.put(_sse("action_proposal", {"proposal_id": str(created["id"]), **proposal}))
                    except Exception as e:
                        print(f"[WARN] 保存 action 提议失败: {e}")

    except asyncio.CancelledError:
        raise  # 不吞掉——外层要靠这个判断这一轮是不是被取消的，不能继续做持久化
    except Exception as e:
        await queue.put(_sse("error", {"code": "agent_error", "message": str(e)}))
        result["error"] = True  # 内部真的出错了，外层要跟"被取消"一样放弃后续持久化
    finally:
        await queue.put(None)


async def stream_chat(
    user_id: UUID,
    conversation_id: UUID,
    user_message: str,
    redis: aioredis.Redis,
    request: Request,
) -> AsyncGenerator[str, None]:
    """主对话流程，yield SSE 格式字符串。

    每个 DB 操作都在独立的 pool.acquire() 块中完成，
    不跨越任何 yield 点持有连接，避免 asyncpg 在生成器暂停时
    将连接释放回连接池的问题。

    request 用来检测客户端是否中途断开（或者前端主动停止生成——服务端
    视角下这是同一件事）：不依赖数据库连接池的状态去猜，直接问
    request.is_disconnected()。检测到断开就 cancel 掉正在跑的生成任务
    （retrieval/SerpAPI/LLM 全部在这个任务的调用链里，cancel 一次就会
    级联传播到底），并放弃这一轮的后续持久化——客户端已经不在了，没有
    "完成一半"的消息值得存进历史记录里。
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

    # 上一轮反思留下的自我提醒（如果有）——读失败不影响主流程，当没有处理
    try:
        self_critique_note = await load_reflection_note(user_id, session_id, redis)
    except Exception as e:
        print(f"[WARN] 加载反思笔记失败: {e}")
        self_critique_note = ""

    # [2.5] 危机判断——两层："关键词字面匹配" 或 "关键词没命中时，LLM 判断
    # 这句话语义上是不是危机信号"。只判断这一次，结果贯穿这一轮对话的全流程
    # （下面给 Agent 参考安全计划、graph_input 的初始 crisis_triggered、
    # 最后要不要追加热线文案、要不要写审计日志），不再让好几个地方各自
    # 重新用关键词扫一遍——那样不仅重复扫描浪费，还会让"到底是不是危机"
    # 这件事在同一轮对话里因为用了不同判断逻辑而得出不一致的结论。
    #
    # 这里会多一次 LLM 调用（关键词没命中时）——对绝大多数正常聊天消息
    # 都会触发，是有意识接受的延迟/成本代价：漏判一个真正有危机信号的
    # 用户，比多等一两百毫秒、多一次很便宜的分类调用严重得多。
    try:
        crisis_triggered, matched_keyword = await assess_crisis(user_message, get_llm())
    except Exception as e:
        print(f"[WARN] 危机判断整体失败，保守起见不算命中（关键词匹配已经在 assess_crisis 内部兜底过一次）: {e}")
        crisis_triggered, matched_keyword = False, None

    # 命中危机时，把用户自己写过的安全计划一并给 Agent 参考，让回应能落到
    # "你安全计划里写的那个方法，要不要现在试试"这种具体程度，而不是每轮
    # 对话都带上（避免闲聊时被突兀地提起）
    if crisis_triggered:
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
        "crisis_triggered": crisis_triggered,
        "agent_type": "",
        "intent_segments": [],
        "segment_responses": [],
        "self_critique_note": self_critique_note,
    }
    graph_config = {"configurable": {"user_id": str(user_id)}}

    # [4] LangGraph 流式推理——真正的检索/搜索/LLM 生成跑在一个独立的
    # asyncio.Task 里（_run_graph_events），另有一个 _watch_disconnect 任务
    # 轮询客户端是否还连着，断开就把生成任务整体 cancel 掉。这里的
    # while 循环只是从 queue 里把生成任务 put 进来的 SSE 消息原样转发出去。
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    result = {"full_response": "", "used_tools": [], "segment_drafts": None}

    graph = await get_graph()
    gen_task = asyncio.create_task(
        _run_graph_events(graph, graph_input, graph_config, pool, user_id, conversation_id, queue, result)
    )
    watcher_task = asyncio.create_task(_watch_disconnect(request, gen_task))

    cancelled = False
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
    finally:
        watcher_task.cancel()
        if not gen_task.done():
            gen_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await gen_task
        with contextlib.suppress(asyncio.CancelledError):
            await watcher_task

    if gen_task.cancelled():
        cancelled = True

    if cancelled:
        # 客户端已经不在了（真断开，或者主动点了停止），没有"生成到一半"
        # 的内容值得存进对话历史——不做危机检测、不落库、不更新任何记忆、
        # 也不起后台任务，安安静静地结束这个生成器。
        print(f"[INFO] 客户端已断开/主动停止生成，放弃本轮后续处理 | user={user_id} conversation={conversation_id}")
        return

    if result.get("error"):
        # 跟原来的行为一致：agent_error 事件已经在上面的循环里转发给前端了，
        # 内部真出错的这一轮直接结束，不继续做危机检测/持久化——那些步骤
        # 依赖 full_response 是完整、可信的，出错之后的内容不满足这个前提。
        return

    full_response = result["full_response"]
    used_tools = result["used_tools"]
    segment_drafts = result["segment_drafts"]

    # [5] 追加热线文案——危机判断本身已经在 [2.5] 做完了（两层：关键词 或
    # LLM 语义判断），这里复用同一个结果，不重新判断一次，避免这一轮对话
    # 里"是不是危机"这件事被两处不同的逻辑各自决定出不一致的答案。
    final_response = append_hotline_if_triggered(full_response, crisis_triggered)
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

    # [6.5] 危机事件审计日志（独立连接）——只有真的命中才写，不是每轮都写
    if crisis_triggered and matched_keyword:
        try:
            async with pool.acquire() as db:
                await save_crisis_event(user_id, message_id, matched_keyword, db)
        except Exception as e:
            print(f"[WARN] 记录危机事件失败: {e}")

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

    # [8] 向量记忆（独立连接）——用独立的总轮数计数器判断要不要存，不能再用
    # len(short_term) 算：短期记忆最多保留最近 10 轮，超过之后 len(short_term)
    # 会卡在容量上限，"每 5 轮存一次"这个判断永远不会再等于整除。
    try:
        turn_count = await increment_turn_count(user_id, session_id, redis)
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

    # [9.4] 用户资料/重要事件提取（后台）——被动提取，不需要用户确认，
    # 写的是低风险的个性化信息（昵称/年龄段/诊断/重要事件），不是会触发
    # 行为的写入动作，跟 propose_* 那套"提议-确认"工具是两条不同的路径。
    asyncio.create_task(
        _profile_background(user_id, user_message, full_response)
    )

    # [9.5] 反思（后台）——不影响这一轮已经发出去的回复，优化的是"下一轮"。
    # 跟情绪提取同一种模式：这一轮的 SSE 已经走完了，起个不等待的后台任务。
    asyncio.create_task(
        _reflection_background(
            user_id, session_id, user_message, final_response, crisis_triggered, segment_drafts, redis,
        )
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


async def _profile_background(
    user_id: UUID,
    user_message: str,
    ai_response: str,
) -> None:
    """跑一次用户资料/重要事件提取，把结果（如果有）写进 user_profiles/
    key_events。失败静默——这是锦上添花的个性化信息，不能因为它出错
    影响主流程。"""
    pool = _db._pool
    if pool is None:
        return
    try:
        result = await extract_profile_info(user_message, ai_response, get_llm())
        async with pool.acquire() as conn:
            await save_profile_updates(user_id, result, conn)
            if result.get("key_event"):
                await save_key_event(user_id, result["key_event"], conn)
    except Exception:
        pass


async def _reflection_background(
    user_id: UUID,
    session_id: str,
    user_message: str,
    final_response: str,
    crisis_triggered: bool,
    segment_drafts: list[dict] | None,
    redis: aioredis.Redis,
) -> None:
    """跑一次反思，把结论（如果有）存进 Redis 给下一轮读。失败静默——
    反思本来就是锦上添花的东西，不能因为它出错影响任何主流程。"""
    try:
        note = await reflect_on_turn(user_message, final_response, crisis_triggered, segment_drafts, get_llm())
        await save_reflection_note(user_id, session_id, note or "", redis)
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
