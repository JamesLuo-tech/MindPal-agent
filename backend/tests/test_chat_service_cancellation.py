"""SSE 客户端断开检测 + 任务取消的测试。

设计：不用数据库连接池的状态判断客户端是否还在，直接轮询 FastAPI
Request.is_disconnected()；检索/搜索/LLM 生成全部跑在一个独立的
asyncio.Task（_run_graph_events）里，检测到断开就整体 cancel 掉这一个
task——asyncio 会自动把取消级联传播到它当前正在 await 的所有子调用，
不需要给 retrieval/SerpAPI/LLM 分别记 task handle。

三层测试：
  1. _watch_disconnect 本身（轮询逻辑、检测到断开后 cancel 目标 task）
  2. _run_graph_events 本身（正常跑完/内部出错/被 cancel 三种收尾路径）
  3. stream_chat 整体编排（正常路径行为不变 + 断线路径放弃后续持久化）
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.chat_service import (
    DISCONNECT_POLL_INTERVAL,
    _run_graph_events,
    _watch_disconnect,
    stream_chat,
)

USER_ID = uuid4()
CONVERSATION_ID = uuid4()


def _fake_request(disconnected_sequence):
    """is_disconnected() 依次返回 disconnected_sequence 里的值，用完之后
    固定返回最后一个值（模拟"一直连着"或"一直断着"）。"""
    seq = list(disconnected_sequence)

    async def _is_disconnected():
        if seq:
            return seq.pop(0)
        return disconnected_sequence[-1] if disconnected_sequence else False

    return SimpleNamespace(is_disconnected=_is_disconnected)


async def _events_from(events: list[dict]):
    for e in events:
        yield e


def _mock_pool():
    """给 _run_graph_events 用的 pool——只有触发 propose_* 工具（走
    on_tool_end 里的 create_proposal 分支）时才会真的用到，这里给一个
    能撑住 async with pool.acquire() 的最小 mock。"""
    pool = MagicMock()
    conn = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=None)
    pool.acquire.return_value = cm
    return pool


# ---------------------------------------------------------------------------
# _watch_disconnect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watch_disconnect_cancels_task_once_client_gone(monkeypatch):
    monkeypatch.setattr("app.services.chat_service.DISCONNECT_POLL_INTERVAL", 0.01)
    request = _fake_request([False, False, True])

    async def _long_running():
        await asyncio.sleep(10)

    target_task = asyncio.create_task(_long_running())

    await _watch_disconnect(request, target_task)

    assert target_task.cancelled() or target_task.cancel()  # 已经被 cancel 掉了
    with pytest.raises(asyncio.CancelledError):
        await target_task


@pytest.mark.asyncio
async def test_watch_disconnect_returns_quietly_when_task_finishes_first(monkeypatch):
    """target task 自己先跑完了（客户端全程没断），watcher 不该报错、
    也不该去 cancel 一个已经结束的 task。"""
    monkeypatch.setattr("app.services.chat_service.DISCONNECT_POLL_INTERVAL", 0.01)
    request = _fake_request([False, False, False])

    async def _quick():
        return "done"

    target_task = asyncio.create_task(_quick())
    await asyncio.sleep(0.03)  # 让它跑完

    await _watch_disconnect(request, target_task)  # 不该抛异常

    assert target_task.done()
    assert not target_task.cancelled()


@pytest.mark.asyncio
async def test_watch_disconnect_tolerates_is_disconnected_errors(monkeypatch):
    """is_disconnected() 本身抛异常时，保守当成"还连着"处理，不能因为探测
    出错就误杀正常请求——继续轮询，而不是直接崩溃或直接 cancel。"""
    monkeypatch.setattr("app.services.chat_service.DISCONNECT_POLL_INTERVAL", 0.01)

    call_count = 0

    async def _flaky_is_disconnected():
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise RuntimeError("探测失败")
        return True

    request = SimpleNamespace(is_disconnected=_flaky_is_disconnected)

    async def _long_running():
        await asyncio.sleep(10)

    target_task = asyncio.create_task(_long_running())
    await _watch_disconnect(request, target_task)

    assert call_count >= 3  # 出错之后确实继续轮询了，不是直接放弃
    with pytest.raises(asyncio.CancelledError):
        await target_task


# ---------------------------------------------------------------------------
# _run_graph_events —— 正常路径
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_graph_events_forwards_message_and_tool_events():
    events = [
        {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_node": "empathy"},
            "data": {"chunk": SimpleNamespace(content="你好")},
        },
        {
            "event": "on_tool_start",
            "name": "lookup",
            "data": {"input": {"query": "失眠"}},
        },
        {
            "event": "on_tool_end",
            "name": "lookup",
            "data": {"output": SimpleNamespace(content="查到的资料")},
        },
    ]
    graph = SimpleNamespace(astream_events=lambda *a, **kw: _events_from(events))
    queue: asyncio.Queue = asyncio.Queue()
    result = {"full_response": "", "used_tools": [], "segment_drafts": None}

    await _run_graph_events(graph, {}, {}, _mock_pool(), USER_ID, CONVERSATION_ID, queue, result)

    items = []
    while not queue.empty():
        items.append(queue.get_nowait())

    assert items[-1] is None  # 结束哨兵
    assert 'event: message\ndata: {"delta": "你好"}\n\n' in items
    assert result["full_response"] == "你好"
    assert result["used_tools"] == ["lookup"]
    assert "error" not in result


@pytest.mark.asyncio
async def test_run_graph_events_filters_non_streamable_nodes():
    """router 自己的分类调用不该被转发成 message 事件。"""
    events = [
        {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_node": "router"},
            "data": {"chunk": SimpleNamespace(content="empathy")},
        },
    ]
    graph = SimpleNamespace(astream_events=lambda *a, **kw: _events_from(events))
    queue: asyncio.Queue = asyncio.Queue()
    result = {"full_response": "", "used_tools": [], "segment_drafts": None}

    await _run_graph_events(graph, {}, {}, _mock_pool(), USER_ID, CONVERSATION_ID, queue, result)

    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    assert items == [None]
    assert result["full_response"] == ""


@pytest.mark.asyncio
async def test_run_graph_events_captures_segment_drafts_from_merge():
    drafts = [{"segment": "a"}, {"segment": "b"}]
    events = [
        {"event": "on_chain_start", "name": "merge", "data": {"input": {"segment_responses": drafts}}},
    ]
    graph = SimpleNamespace(astream_events=lambda *a, **kw: _events_from(events))
    queue: asyncio.Queue = asyncio.Queue()
    result = {"full_response": "", "used_tools": [], "segment_drafts": None}

    await _run_graph_events(graph, {}, {}, _mock_pool(), USER_ID, CONVERSATION_ID, queue, result)

    assert result["segment_drafts"] == drafts


# ---------------------------------------------------------------------------
# _run_graph_events —— 内部出错
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_graph_events_puts_error_event_and_marks_result_on_exception():
    async def _raising_events():
        raise RuntimeError("图跑挂了")
        yield  # pragma: no cover - 让这是个 async generator

    graph = SimpleNamespace(astream_events=lambda *a, **kw: _raising_events())
    queue: asyncio.Queue = asyncio.Queue()
    result = {"full_response": "", "used_tools": [], "segment_drafts": None}

    await _run_graph_events(graph, {}, {}, _mock_pool(), USER_ID, CONVERSATION_ID, queue, result)

    items = []
    while not queue.empty():
        items.append(queue.get_nowait())

    assert items[-1] is None
    assert any("agent_error" in i for i in items if isinstance(i, str))
    assert result["error"] is True


# ---------------------------------------------------------------------------
# _run_graph_events —— 被取消
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_graph_events_reraises_cancelled_but_still_puts_sentinel():
    """被 cancel 时：CancelledError 要真的往外传播（外层要靠这个判断"这一轮
    被取消了，不能继续持久化"），但 finally 里的哨兵还是要放，不然消费者
    会永远卡在 queue.get() 上。"""
    started = asyncio.Event()

    async def _slow_events():
        yield {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_node": "empathy"},
            "data": {"chunk": SimpleNamespace(content="第一段")},
        }
        started.set()
        await asyncio.sleep(10)  # 卡在这里等着被 cancel
        yield {"event": "on_chat_model_stream", "metadata": {}, "data": {"chunk": SimpleNamespace(content="不该到达")}}

    graph = SimpleNamespace(astream_events=lambda *a, **kw: _slow_events())
    queue: asyncio.Queue = asyncio.Queue()
    result = {"full_response": "", "used_tools": [], "segment_drafts": None}

    task = asyncio.create_task(
        _run_graph_events(graph, {}, {}, _mock_pool(), USER_ID, CONVERSATION_ID, queue, result)
    )
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert task.cancelled()
    assert "error" not in result
    # 哨兵最终还是被放进了 queue（finally 里执行），消费者不会被永远卡住
    last_item = None
    while not queue.empty():
        last_item = queue.get_nowait()
    assert last_item is None


# ---------------------------------------------------------------------------
# stream_chat —— 整体编排
# ---------------------------------------------------------------------------


def _patch_chat_service_deps(**overrides):
    """stream_chat 依赖的一大堆外部函数，统一给出合理的默认 mock，
    调用方按需覆盖。"""
    defaults = dict(
        _check_rate_limit=AsyncMock(return_value=True),
        load_short_term=AsyncMock(return_value=[]),
        load_long_term=AsyncMock(return_value=""),
        load_reflection_note=AsyncMock(return_value=""),
        get_graph=AsyncMock(),
        assess_crisis=AsyncMock(return_value=(False, None)),
        append_hotline_if_triggered=MagicMock(side_effect=lambda text, triggered: text),
        _save_messages=AsyncMock(return_value=uuid4()),
        save_crisis_event=AsyncMock(),
        save_short_term=AsyncMock(),
        increment_turn_count=AsyncMock(return_value=1),
        save_memory=AsyncMock(),
    )
    defaults.update(overrides)
    return defaults


@pytest.mark.asyncio
async def test_stream_chat_happy_path_still_forwards_events_and_persists():
    """重构后正常路径的行为不变：事件照常转发，最后照常持久化 + done。"""
    events = [
        {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_node": "empathy"},
            "data": {"chunk": SimpleNamespace(content="你好呀")},
        },
    ]
    fake_graph = SimpleNamespace(astream_events=lambda *a, **kw: _events_from(events))
    deps = _patch_chat_service_deps(get_graph=AsyncMock(return_value=fake_graph))

    with (
        patch("app.services.chat_service._db") as mock_db_module,
        patch("app.services.chat_service._check_rate_limit", deps["_check_rate_limit"]),
        patch("app.services.chat_service.load_short_term", deps["load_short_term"]),
        patch("app.services.chat_service.load_long_term", deps["load_long_term"]),
        patch("app.services.chat_service.load_reflection_note", deps["load_reflection_note"]),
        patch("app.services.chat_service.get_graph", deps["get_graph"]),
        patch("app.services.chat_service.assess_crisis", deps["assess_crisis"]),
        patch("app.services.chat_service.append_hotline_if_triggered", deps["append_hotline_if_triggered"]),
        patch("app.services.chat_service._save_messages", deps["_save_messages"]),
        patch("app.services.chat_service.save_short_term", deps["save_short_term"]),
        patch("app.services.chat_service.increment_turn_count", deps["increment_turn_count"]),
        patch("app.services.chat_service.save_memory", deps["save_memory"]),
        # [9]/[9.4]/[9.5] 是不等待的后台任务，跟这次改动无关，只是不能让它们
        # 在单测里真的去调 LLM/写库。
        patch("app.services.chat_service._emotion_background", AsyncMock()),
        patch("app.services.chat_service._profile_background", AsyncMock()),
        patch("app.services.chat_service._reflection_background", AsyncMock()),
    ):
        mock_db_module._pool = _mock_pool()
        request = _fake_request([False] * 10)  # 全程没断开

        collected = []
        async for chunk in stream_chat(USER_ID, CONVERSATION_ID, "你好", AsyncMock(), request):
            collected.append(chunk)

    assert any('"delta": "你好呀"' in c for c in collected)
    assert any(c.startswith("event: done") for c in collected)
    deps["_save_messages"].assert_awaited_once()


@pytest.mark.asyncio
async def test_stream_chat_abandons_turn_when_client_disconnects_mid_generation():
    """核心场景：生成到一半客户端断开——生成任务要被 cancel，且不能再往下
    做危机检测/持久化/记忆更新，因为客户端已经不在了。"""
    started = asyncio.Event()

    async def _slow_events():
        yield {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_node": "empathy"},
            "data": {"chunk": SimpleNamespace(content="说到一半")},
        }
        started.set()
        await asyncio.sleep(10)  # 模拟还在跑 retrieval/LLM，等着被 cancel

    fake_graph = SimpleNamespace(astream_events=lambda *a, **kw: _slow_events())
    deps = _patch_chat_service_deps(get_graph=AsyncMock(return_value=fake_graph))

    disconnect_flag = {"value": False}

    async def _is_disconnected():
        return disconnect_flag["value"]

    request = SimpleNamespace(is_disconnected=_is_disconnected)

    async def _flip_disconnect_once_started():
        await started.wait()
        disconnect_flag["value"] = True

    with (
        patch("app.services.chat_service._db") as mock_db_module,
        patch("app.services.chat_service.DISCONNECT_POLL_INTERVAL", 0.01),
        patch("app.services.chat_service._check_rate_limit", deps["_check_rate_limit"]),
        patch("app.services.chat_service.load_short_term", deps["load_short_term"]),
        patch("app.services.chat_service.load_long_term", deps["load_long_term"]),
        patch("app.services.chat_service.load_reflection_note", deps["load_reflection_note"]),
        patch("app.services.chat_service.get_graph", deps["get_graph"]),
        patch("app.services.chat_service.assess_crisis", deps["assess_crisis"]),
        patch("app.services.chat_service.append_hotline_if_triggered", deps["append_hotline_if_triggered"]),
        patch("app.services.chat_service._save_messages", deps["_save_messages"]),
        patch("app.services.chat_service.save_short_term", deps["save_short_term"]),
        patch("app.services.chat_service.increment_turn_count", deps["increment_turn_count"]),
        patch("app.services.chat_service.save_memory", deps["save_memory"]),
    ):
        mock_db_module._pool = _mock_pool()
        flipper = asyncio.create_task(_flip_disconnect_once_started())

        collected = []
        async for chunk in stream_chat(USER_ID, CONVERSATION_ID, "你好", AsyncMock(), request):
            collected.append(chunk)

        await flipper

    # 断开之前已经发出去的那一段内容，前端确实会收到（这是合理的：内容
    # 已经发出去了），但断开之后不该再有 done 事件，更不该有任何持久化。
    assert any('"delta": "说到一半"' in c for c in collected)
    assert not any(c.startswith("event: done") for c in collected)
    deps["_save_messages"].assert_not_awaited()
    deps["save_short_term"].assert_not_awaited()
    deps["save_memory"].assert_not_awaited()
