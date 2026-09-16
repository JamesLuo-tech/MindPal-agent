"""多意图拆分路径的测试：router 的分段解析、route_after_router 的
Send 扇出、run_segment 的本地工具循环、merge 的合并/透传逻辑。

覆盖的核心行为约定：
  - 单意图（绝大多数消息）必须跟这次改动之前完全一样，零额外开销
  - 只有清楚识别出两段格式时才真正拆分，识别失败一律整句话当一段兜底
  - run_segment 用本地消息列表跑自己的工具循环，不碰共享的 state["messages"]
  - merge 只有一段时直接透传、不额外调 LLM；两段以上才真正合并
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Send


# ---------------------------------------------------------------------------
# _parse_router_response
# ---------------------------------------------------------------------------


def test_parse_router_response_single_label():
    from app.agent.graph import _parse_router_response

    segments = _parse_router_response("empathy", "我最近好累")
    assert segments == [{"agent_type": "empathy", "text": "我最近好累"}]


def test_parse_router_response_falls_back_on_garbage():
    from app.agent.graph import _parse_router_response

    segments = _parse_router_response("不知道说什么", "随便说点什么")
    assert segments == [{"agent_type": "empathy", "text": "随便说点什么"}]


def test_parse_router_response_falls_back_on_empty():
    from app.agent.graph import _parse_router_response

    segments = _parse_router_response("", "随便")
    assert segments == [{"agent_type": "empathy", "text": "随便"}]


def test_parse_router_response_parses_two_segments():
    from app.agent.graph import _parse_router_response

    content = "empathy: 我今天挺难受的\naction: 帮我记一下心情"
    segments = _parse_router_response(content, "我今天挺难受的，帮我记一下心情")
    assert segments == [
        {"agent_type": "empathy", "text": "我今天挺难受的"},
        {"agent_type": "action", "text": "帮我记一下心情"},
    ]


def test_parse_router_response_is_case_insensitive():
    from app.agent.graph import _parse_router_response

    content = "EMPATHY: 我很难受\nACTION: 记一下"
    segments = _parse_router_response(content, "原句")
    assert [s["agent_type"] for s in segments] == ["empathy", "action"]


def test_parse_router_response_caps_at_two_segments():
    from app.agent.graph import _parse_router_response

    content = "empathy: 一\nknowledge: 二\naction: 三"
    segments = _parse_router_response(content, "原句")
    assert len(segments) == 2


def test_parse_router_response_single_matched_line_falls_back_to_whole_message():
    """只识别出一行合法格式（不满足"两段"这个门槛）时，应该整句话走单段兜底，
    不能只用识别出的那一段——半吊子的多段格式不算真正的拆分。"""
    from app.agent.graph import _parse_router_response

    content = "empathy: 我今天挺难受的"
    fallback = "我今天挺难受的，帮我记一下心情"
    segments = _parse_router_response(content, fallback)
    assert len(segments) == 1
    assert segments[0]["text"] == fallback  # 用的是完整原句，不是识别出的半句


# ---------------------------------------------------------------------------
# router_node 接入 intent_segments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_router_sets_single_segment_for_normal_message():
    from app.agent.graph import router_node

    mock_response = AsyncMock()
    mock_response.content = "knowledge"
    state = {
        "messages": [HumanMessage(content="失眠怎么办")],
        "user_id": "u1", "conversation_id": "c1",
        "long_term_memory": "", "crisis_triggered": False, "agent_type": "",
    }
    with patch("app.agent.graph.get_llm") as mock_get_llm:
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_get_llm.return_value = mock_llm
        result = await router_node(state)

    assert result["intent_segments"] == [{"agent_type": "knowledge", "text": "失眠怎么办"}]
    assert result["agent_type"] == "knowledge"


@pytest.mark.asyncio
async def test_router_sets_two_segments_for_multi_intent_message():
    from app.agent.graph import router_node

    mock_response = AsyncMock()
    mock_response.content = "empathy: 我今天挺难受的\naction: 帮我记一下心情"
    state = {
        "messages": [HumanMessage(content="我今天挺难受的，帮我记一下心情")],
        "user_id": "u1", "conversation_id": "c1",
        "long_term_memory": "", "crisis_triggered": False, "agent_type": "",
    }
    with patch("app.agent.graph.get_llm") as mock_get_llm:
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_get_llm.return_value = mock_llm
        result = await router_node(state)

    assert result["intent_segments"] == [
        {"agent_type": "empathy", "text": "我今天挺难受的"},
        {"agent_type": "action", "text": "帮我记一下心情"},
    ]
    assert result["agent_type"] == "empathy"  # 第一段的标签，供单段路径兼容


@pytest.mark.asyncio
async def test_router_crisis_path_sets_single_segment_without_calling_llm():
    from app.agent.graph import router_node

    state = {
        "messages": [HumanMessage(content="我不想活了")],
        "user_id": "u1", "conversation_id": "c1",
        "long_term_memory": "", "crisis_triggered": False, "agent_type": "",
    }
    result = await router_node(state)  # 不 mock get_llm，命中危机词应该完全不调用 LLM
    assert result["intent_segments"] == [{"agent_type": "empathy", "text": "我不想活了"}]
    assert result["crisis_triggered"] is True


# ---------------------------------------------------------------------------
# route_after_router
# ---------------------------------------------------------------------------


def test_route_after_router_single_segment_returns_plain_string():
    from app.agent.graph import route_after_router

    state = {"intent_segments": [{"agent_type": "knowledge", "text": "x"}], "agent_type": "knowledge"}
    assert route_after_router(state) == "knowledge"


def test_route_after_router_no_segments_defaults_to_empathy():
    from app.agent.graph import route_after_router

    state = {"intent_segments": [], "agent_type": "empathy"}
    assert route_after_router(state) == "empathy"


def test_route_after_router_multi_segment_returns_send_list():
    from app.agent.graph import route_after_router

    segments = [
        {"agent_type": "empathy", "text": "我今天挺难受的"},
        {"agent_type": "action", "text": "帮我记一下心情"},
    ]
    state = {"intent_segments": segments, "agent_type": "empathy", "messages": []}
    result = route_after_router(state)

    assert len(result) == 2
    assert all(isinstance(s, Send) for s in result)
    assert [s.node for s in result] == ["run_segment", "run_segment"]
    assert [s.arg["current_segment"] for s in result] == segments


# ---------------------------------------------------------------------------
# run_segment_node：本地工具循环，不碰共享的 state["messages"]
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_segment_node_empathy_no_tools():
    from app.agent.graph import run_segment_node

    response = AIMessage(content="听起来今天很不容易", tool_calls=[])
    state = {
        "messages": [HumanMessage(content="我今天挺难受的，帮我记一下心情")],
        "long_term_memory": "",
        "current_segment": {"agent_type": "empathy", "text": "我今天挺难受的"},
    }
    with patch("app.agent.graph._segment_llm") as mock_segment_llm:
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=response)
        mock_segment_llm.return_value = mock_llm
        result = await run_segment_node(state)

    assert result["segment_responses"] == [{
        "agent_type": "empathy", "status": "success",
        "text": "听起来今天很不容易", "error": None, "retry_count": 0,
    }]
    # 只调用了一次 LLM（没有 tool_calls，不需要第二轮）
    assert mock_llm.ainvoke.await_count == 1


@pytest.mark.asyncio
async def test_run_segment_node_runs_local_tool_loop_and_does_not_touch_shared_messages():
    """action 段带工具调用：第一轮返回 tool_calls，执行工具后第二轮拿到最终文字。
    整个过程只在本地 local_messages 里进行，不应该往 state["messages"] 里写东西
    ——run_segment 的返回值里不应该有 "messages" 这个 key。"""
    from app.agent.graph import run_segment_node

    tool_call_response = AIMessage(
        content="",
        tool_calls=[{"id": "call_1", "name": "propose_record_mood", "args": {"mood": 4}, "type": "tool_call"}],
    )
    final_response = AIMessage(content="好，已经帮你整理了一条记录草稿", tool_calls=[])

    mock_tool = AsyncMock()
    mock_tool.ainvoke = AsyncMock(return_value="tool result")

    state = {
        "messages": [HumanMessage(content="帮我记一下心情")],
        "long_term_memory": "",
        "current_segment": {"agent_type": "action", "text": "帮我记一下心情"},
    }

    with (
        patch("app.agent.graph._segment_llm") as mock_segment_llm,
        patch("app.agent.graph._segment_tools_by_name", return_value={"propose_record_mood": mock_tool}),
    ):
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=[tool_call_response, final_response])
        mock_segment_llm.return_value = mock_llm
        result = await run_segment_node(state)

    assert result["segment_responses"] == [{
        "agent_type": "action", "status": "success",
        "text": "好，已经帮你整理了一条记录草稿", "error": None, "retry_count": 0,
    }]
    assert "messages" not in result  # 没有直接写共享的 messages
    assert mock_llm.ainvoke.await_count == 2  # 两轮：工具调用 + 拿最终文字
    mock_tool.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_segment_node_stops_at_max_rounds_instead_of_looping_forever():
    """LLM 一直返回 tool_calls 不收敛时，要有防御性上限，不能死循环。"""
    from app.agent.graph import _SEGMENT_MAX_TOOL_ROUNDS, run_segment_node

    tool_call_response = AIMessage(
        content="",
        tool_calls=[{"id": "call_x", "name": "propose_record_mood", "args": {}, "type": "tool_call"}],
    )
    mock_tool = AsyncMock()
    mock_tool.ainvoke = AsyncMock(return_value="tool result")

    state = {
        "messages": [HumanMessage(content="帮我记一下心情")],
        "long_term_memory": "",
        "current_segment": {"agent_type": "action", "text": "帮我记一下心情"},
    }

    with (
        patch("app.agent.graph._segment_llm") as mock_segment_llm,
        patch("app.agent.graph._segment_tools_by_name", return_value={"propose_record_mood": mock_tool}),
    ):
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=tool_call_response)  # 每次都返回 tool_calls，永不收敛
        mock_segment_llm.return_value = mock_llm
        result = await run_segment_node(state)

    assert mock_llm.ainvoke.await_count == _SEGMENT_MAX_TOOL_ROUNDS  # 没有超过上限
    assert result["segment_responses"][0]["agent_type"] == "action"


# ---------------------------------------------------------------------------
# _is_retryable_error —— 区分"值得重试"和"重试也没用"的错误
# ---------------------------------------------------------------------------


def test_is_retryable_error_recognizes_status_code_attribute():
    from app.agent.graph import _is_retryable_error

    class FakeHTTPError(Exception):
        status_code = 429

    assert _is_retryable_error(FakeHTTPError()) is True


def test_is_retryable_error_recognizes_status_code_on_response_attribute():
    from app.agent.graph import _is_retryable_error

    class FakeResponse:
        status_code = 503

    class FakeHTTPError(Exception):
        response = FakeResponse()

    assert _is_retryable_error(FakeHTTPError()) is True


def test_is_retryable_error_recognizes_timeout_error():
    from app.agent.graph import _is_retryable_error
    assert _is_retryable_error(TimeoutError()) is True
    assert _is_retryable_error(asyncio.TimeoutError()) is True


def test_is_retryable_error_recognizes_error_class_name_heuristic():
    from app.agent.graph import _is_retryable_error

    class RateLimitError(Exception):
        pass

    class APITimeoutError(Exception):
        pass

    assert _is_retryable_error(RateLimitError()) is True
    assert _is_retryable_error(APITimeoutError()) is True


def test_is_retryable_error_returns_false_for_deterministic_errors():
    from app.agent.graph import _is_retryable_error
    assert _is_retryable_error(ValueError("缺少必填参数")) is False
    assert _is_retryable_error(KeyError("agent_type")) is False

    class PermissionDeniedError(Exception):
        status_code = 403

    assert _is_retryable_error(PermissionDeniedError()) is False


# ---------------------------------------------------------------------------
# run_segment_node —— 失败降级 + 退避重试（核心：某一段失败不该让整个
# Send 并发扇出一起挂掉，异常必须被兜在这个节点内部）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_segment_node_retries_retryable_error_and_recovers():
    """第一次遇到可重试错误，第二次成功——应该正常返回 success，
    retry_count 记录实际重试了几次。"""
    from app.agent.graph import run_segment_node

    class FlakyTimeout(Exception):
        pass

    ok_response = AIMessage(content="第二次成功了", tool_calls=[])
    state = {
        "messages": [HumanMessage(content="随便问点什么")],
        "long_term_memory": "",
        "current_segment": {"agent_type": "knowledge", "text": "随便问点什么"},
    }
    with (
        patch("app.agent.graph._segment_llm") as mock_segment_llm,
        patch("app.agent.graph._SEGMENT_RETRY_BASE_DELAY", 0),  # 单测不真的等
    ):
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=[FlakyTimeout("超时了"), ok_response])
        mock_segment_llm.return_value = mock_llm
        result = await run_segment_node(state)

    assert result["segment_responses"] == [{
        "agent_type": "knowledge", "status": "success",
        "text": "第二次成功了", "error": None, "retry_count": 1,
    }]


@pytest.mark.asyncio
async def test_run_segment_node_gives_up_after_max_retries_and_degrades_instead_of_raising():
    """可重试错误但一直失败——重试用尽后必须正常返回 status=failed，
    绝不能让异常从这个节点里跑出去（那样会连累 Send 并发扇出的其他分支）。"""
    from app.agent.graph import _SEGMENT_MAX_RETRIES, run_segment_node

    class AlwaysTimeout(Exception):
        pass

    state = {
        "messages": [HumanMessage(content="随便问点什么")],
        "long_term_memory": "",
        "current_segment": {"agent_type": "knowledge", "text": "随便问点什么"},
    }
    with (
        patch("app.agent.graph._segment_llm") as mock_segment_llm,
        patch("app.agent.graph._SEGMENT_RETRY_BASE_DELAY", 0),
    ):
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=AlwaysTimeout("一直超时"))
        mock_segment_llm.return_value = mock_llm
        result = await run_segment_node(state)  # 不该抛异常

    resp = result["segment_responses"][0]
    assert resp["status"] == "failed"
    assert resp["agent_type"] == "knowledge"
    assert "一直超时" in resp["error"]
    assert resp["retry_count"] == _SEGMENT_MAX_RETRIES
    # 一次初始尝试 + _SEGMENT_MAX_RETRIES 次重试
    assert mock_llm.ainvoke.await_count == _SEGMENT_MAX_RETRIES + 1


@pytest.mark.asyncio
async def test_run_segment_node_does_not_retry_non_retryable_error():
    """确定性错误（比如参数错误）不该白白重试——第一次失败就该直接降级，
    不多花 LLM 调用次数。"""
    from app.agent.graph import run_segment_node

    state = {
        "messages": [HumanMessage(content="随便问点什么")],
        "long_term_memory": "",
        "current_segment": {"agent_type": "knowledge", "text": "随便问点什么"},
    }
    with patch("app.agent.graph._segment_llm") as mock_segment_llm:
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=ValueError("参数不对"))
        mock_segment_llm.return_value = mock_llm
        result = await run_segment_node(state)

    resp = result["segment_responses"][0]
    assert resp["status"] == "failed"
    assert resp["retry_count"] == 0
    assert mock_llm.ainvoke.await_count == 1  # 没有重试


@pytest.mark.asyncio
async def test_run_segment_node_action_type_never_retries_even_on_retryable_error():
    """action 段一失败就直接降级，即使错误本身是可重试类型——因为
    propose_* 工具调用是有副作用的（成功会真的在 action_proposals 表里
    生成一条提议卡片），重试有制造重复提议卡片的风险，不能简单重试。"""
    from app.agent.graph import run_segment_node

    class RateLimitError(Exception):
        pass

    state = {
        "messages": [HumanMessage(content="帮我记一下心情")],
        "long_term_memory": "",
        "current_segment": {"agent_type": "action", "text": "帮我记一下心情"},
    }
    with patch("app.agent.graph._segment_llm") as mock_segment_llm:
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=RateLimitError("限流了"))
        mock_segment_llm.return_value = mock_llm
        result = await run_segment_node(state)

    resp = result["segment_responses"][0]
    assert resp["status"] == "failed"
    assert resp["retry_count"] == 0
    assert mock_llm.ainvoke.await_count == 1  # action 段不重试，即使是可重试错误类型


# ---------------------------------------------------------------------------
# merge_node
# ---------------------------------------------------------------------------


def _success(agent_type: str, text: str, retry_count: int = 0) -> dict:
    return {"agent_type": agent_type, "status": "success", "text": text, "error": None, "retry_count": retry_count}


def _failed(agent_type: str, error: str = "boom", retry_count: int = 2) -> dict:
    return {"agent_type": agent_type, "status": "failed", "text": "", "error": error, "retry_count": retry_count}


@pytest.mark.asyncio
async def test_merge_node_passes_through_single_response_without_calling_llm():
    from app.agent.graph import merge_node

    state = {"segment_responses": [_success("empathy", "听起来今天很不容易")]}
    with patch("app.agent.graph._get_empathy_llm") as mock_get_empathy_llm:
        result = await merge_node(state)
        mock_get_empathy_llm.assert_not_called()  # 只有一段不该多花一次 LLM 调用

    assert result["messages"][0].content == "听起来今天很不容易"


@pytest.mark.asyncio
async def test_merge_node_handles_empty_responses_without_crashing():
    from app.agent.graph import merge_node

    result = await merge_node({"segment_responses": []})
    assert result["messages"][0].content == ""


@pytest.mark.asyncio
async def test_merge_node_merges_multiple_responses_via_llm():
    from app.agent.graph import merge_node

    merged_response = AsyncMock()
    merged_response.content = "今天听起来挺不容易的，我已经帮你把心情记下来了"

    state = {
        "segment_responses": [
            _success("empathy", "听起来今天很不容易"),
            _success("action", "好，已经帮你整理了一条记录草稿"),
        ],
    }
    with patch("app.agent.graph._get_empathy_llm") as mock_get_empathy_llm:
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=merged_response)
        mock_get_empathy_llm.return_value = mock_llm
        result = await merge_node(state)

    assert result["messages"][0].content == "今天听起来挺不容易的，我已经帮你把心情记下来了"
    sent_prompt = mock_llm.ainvoke.call_args[0][0]
    assert "听起来今天很不容易" in sent_prompt  # 两段草稿都被送进了合并 prompt
    assert "好，已经帮你整理了一条记录草稿" in sent_prompt


# ---------------------------------------------------------------------------
# merge_node —— 部分/全部分支失败时的 graceful degradation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_node_degrades_gracefully_when_one_segment_fails():
    """核心场景：empathy 成功、knowledge 失败——用户应该拿到 empathy 的
    正常回复 + 一句口语化的降级提示，而不是整轮报错。"""
    from app.agent.graph import merge_node

    state = {
        "segment_responses": [
            _success("empathy", "听起来今天很不容易"),
            _failed("knowledge"),
        ],
    }
    with patch("app.agent.graph._get_empathy_llm") as mock_get_empathy_llm:
        result = await merge_node(state)
        # 只有一个成功分支，不该多花一次"合并"的 LLM 调用
        mock_get_empathy_llm.assert_not_called()

    text = result["messages"][0].content
    assert "听起来今天很不容易" in text
    assert "没查到" in text or "查" in text  # knowledge 失败的降级提示


@pytest.mark.asyncio
async def test_merge_node_merges_succeeded_and_notes_failed_when_multiple_of_each():
    from app.agent.graph import merge_node

    merged_response = AsyncMock()
    merged_response.content = "合并后的正文"
    state = {
        "segment_responses": [
            _success("empathy", "共情草稿"),
            _success("action", "行动草稿"),
            _failed("knowledge"),
        ],
    }
    with patch("app.agent.graph._get_empathy_llm") as mock_get_empathy_llm:
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=merged_response)
        mock_get_empathy_llm.return_value = mock_llm
        result = await merge_node(state)

    text = result["messages"][0].content
    assert text.startswith("合并后的正文")  # 只用成功分支合并，失败分支不参与合并 prompt
    sent_prompt = mock_llm.ainvoke.call_args[0][0]
    assert "共情草稿" in sent_prompt
    assert "行动草稿" in sent_prompt
    assert "boom" not in sent_prompt  # 失败分支的 error 信息不该泄露进合并 prompt


@pytest.mark.asyncio
async def test_merge_node_falls_back_to_apology_when_all_segments_failed():
    """全部分支都失败——没有任何可用内容，整体退化成一句抱歉，而不是让
    这一轮变成生硬的系统报错。"""
    from app.agent.graph import merge_node

    state = {"segment_responses": [_failed("empathy"), _failed("knowledge")]}
    result = await merge_node(state)

    from app.agent.graph import _ALL_SEGMENTS_FAILED_FALLBACK
    assert result["messages"][0].content == _ALL_SEGMENTS_FAILED_FALLBACK


# ---------------------------------------------------------------------------
# 图结构：新节点/新边接进去之后图还能正常编译
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graph_has_run_segment_and_merge_nodes():
    from app.agent.graph import build_graph

    graph = await build_graph()
    node_names = set(graph.nodes.keys())
    for expected in ("run_segment", "merge"):
        assert expected in node_names, f"缺少节点: {expected}"
