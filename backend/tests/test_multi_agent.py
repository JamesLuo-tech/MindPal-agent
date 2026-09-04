import pytest
from app.agent.graph import AgentState


def test_agent_state_has_agent_type_field():
    """AgentState 必须包含 agent_type 字段。"""
    fields = AgentState.__annotations__
    assert "agent_type" in fields, "AgentState 缺少 agent_type 字段"


def test_agent_state_has_crisis_triggered_field():
    fields = AgentState.__annotations__
    assert "crisis_triggered" in fields


from unittest.mock import AsyncMock, patch
from langchain_core.messages import AIMessage, HumanMessage


@pytest.mark.asyncio
async def test_router_detects_crisis_keyword():
    """危机关键词命中时，router 应返回 empathy + crisis_triggered=True。"""
    from app.agent.graph import router_node

    state = {
        "messages": [HumanMessage(content="我不想活了")],
        "user_id": "u1",
        "conversation_id": "c1",
        "long_term_memory": "",
        "crisis_triggered": False,
        "agent_type": "",
    }
    result = await router_node(state)
    assert result["agent_type"] == "empathy"
    assert result["crisis_triggered"] is True


@pytest.mark.asyncio
async def test_router_llm_returns_empathy():
    """LLM 返回 empathy 时，router 应路由到 empathy。"""
    from app.agent.graph import router_node

    mock_response = AsyncMock()
    mock_response.content = "empathy"

    state = {
        "messages": [HumanMessage(content="我最近好累")],
        "user_id": "u1",
        "conversation_id": "c1",
        "long_term_memory": "",
        "crisis_triggered": False,
        "agent_type": "",
    }

    with patch("app.agent.graph.get_llm") as mock_get_llm:
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_get_llm.return_value = mock_llm
        result = await router_node(state)

    assert result["agent_type"] == "empathy"
    assert result["crisis_triggered"] is False


@pytest.mark.asyncio
async def test_router_defaults_to_empathy_on_unknown_response():
    """LLM 返回无法解析的内容时，router 默认路由到 empathy。"""
    from app.agent.graph import router_node

    mock_response = AsyncMock()
    mock_response.content = "unclear response xyz"

    state = {
        "messages": [HumanMessage(content="随便说点什么")],
        "user_id": "u1",
        "conversation_id": "c1",
        "long_term_memory": "",
        "crisis_triggered": False,
        "agent_type": "",
    }

    with patch("app.agent.graph.get_llm") as mock_get_llm:
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_get_llm.return_value = mock_llm
        result = await router_node(state)

    assert result["agent_type"] == "empathy"


@pytest.mark.asyncio
async def test_router_defaults_to_empathy_on_empty_response():
    """LLM 返回空字符串时，router 默认路由到 empathy 而不是崩溃。"""
    from app.agent.graph import router_node

    mock_response = AsyncMock()
    mock_response.content = ""

    state = {
        "messages": [HumanMessage(content="随便")],
        "user_id": "u1",
        "conversation_id": "c1",
        "long_term_memory": "",
        "crisis_triggered": False,
        "agent_type": "",
    }

    with patch("app.agent.graph.get_llm") as mock_get_llm:
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_get_llm.return_value = mock_llm
        result = await router_node(state)

    assert result["agent_type"] == "empathy"


def test_format_router_history_empty_for_first_message():
    """对话第一句时（messages 里只有当前这一句），历史应该是明确的"没有历史"提示，不是空字符串。"""
    from app.agent.graph import _format_router_history

    result = _format_router_history([HumanMessage(content="你好")])
    assert "没有更早的历史" in result


def test_format_router_history_includes_recent_turns():
    """应该把最近几轮历史（不含当前这句）格式化成"角色：内容"的形式。"""
    from app.agent.graph import _format_router_history

    messages = [
        HumanMessage(content="我最近在练正念冥想"),
        AIMessage(content="听起来是个不错的方法，感觉怎么样"),
        HumanMessage(content="那个方法有用吗"),  # 当前这句，不应该出现在历史里
    ]
    result = _format_router_history(messages)
    assert "用户：我最近在练正念冥想" in result
    assert "AI：听起来是个不错的方法，感觉怎么样" in result
    assert "那个方法有用吗" not in result  # 当前消息被排除在历史之外


def test_format_router_history_caps_to_recent_turns():
    """历史轮数超过上限时，只保留最近几轮，不能无限拼接拖慢分类调用。"""
    from app.agent.graph import _ROUTER_HISTORY_TURNS, _format_router_history

    # 造比上限多一倍的历史轮数，最早的几轮应该被裁掉
    messages = []
    for i in range(_ROUTER_HISTORY_TURNS * 2 + 2):
        messages.append(HumanMessage(content=f"很久以前的第 {i} 句话"))
    messages.append(HumanMessage(content="当前这句话"))

    result = _format_router_history(messages)
    assert "很久以前的第 0 句话" not in result  # 最早的一轮应该被裁掉
    assert f"很久以前的第 {_ROUTER_HISTORY_TURNS * 2 + 1} 句话" in result  # 最近一轮还在


def test_format_router_history_truncates_long_messages():
    """单条历史消息太长时要截断，不能让一条长倾诉把分类 prompt 撑爆。"""
    from app.agent.graph import _ROUTER_HISTORY_MSG_MAXLEN, _format_router_history

    long_msg = "很难受" * 200  # 明显超过截断长度
    messages = [HumanMessage(content=long_msg), HumanMessage(content="当前这句")]

    result = _format_router_history(messages)
    assert len(result) < len(long_msg)  # 确实被截断了，不是原样塞进去


@pytest.mark.asyncio
async def test_router_prompt_includes_history_and_current_message():
    """router 实际发给 LLM 的 prompt 里应该同时带上历史和当前消息，不是只有当前这一句。"""
    from app.agent.graph import router_node

    mock_response = AsyncMock()
    mock_response.content = "knowledge"

    state = {
        "messages": [
            HumanMessage(content="我最近在练正念冥想"),
            AIMessage(content="听起来是个不错的方法"),
            HumanMessage(content="那个方法有用吗"),
        ],
        "user_id": "u1",
        "conversation_id": "c1",
        "long_term_memory": "",
        "crisis_triggered": False,
        "agent_type": "",
    }

    with patch("app.agent.graph.get_llm") as mock_get_llm:
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_get_llm.return_value = mock_llm
        await router_node(state)

    sent_prompt = mock_llm.ainvoke.call_args[0][0]
    assert "我最近在练正念冥想" in sent_prompt  # 历史在
    assert "那个方法有用吗" in sent_prompt  # 当前消息也在


@pytest.mark.asyncio
async def test_graph_compiles_successfully():
    """图应能成功编译，不抛出异常。"""
    from app.agent.graph import build_graph
    graph = await build_graph()
    assert graph is not None


@pytest.mark.asyncio
async def test_graph_has_all_nodes():
    """图应包含 router、empathy、knowledge、tools、crisis_check 节点。"""
    from app.agent.graph import build_graph
    graph = await build_graph()
    node_names = set(graph.nodes.keys())
    for expected in ("router", "empathy", "knowledge", "tools", "crisis_check"):
        assert expected in node_names, f"缺少节点: {expected}"


def test_should_continue_knowledge_routes_to_tools_when_tool_calls():
    """当 AIMessage 有 tool_calls 时，应路由到 tools。"""
    from app.agent.graph import should_continue_knowledge

    state = {
        "messages": [
            AIMessage(content="response", tool_calls=[{"id": "1", "name": "lookup", "args": {}, "type": "tool_call"}])
        ],
        "user_id": "u1",
        "conversation_id": "c1",
        "long_term_memory": "",
        "crisis_triggered": False,
        "agent_type": "knowledge",
    }
    assert should_continue_knowledge(state) == "tools"


def test_should_continue_knowledge_routes_to_crisis_check_without_tool_calls():
    """当 AIMessage 没有 tool_calls 时，应路由到 crisis_check。"""
    from app.agent.graph import should_continue_knowledge

    state = {
        "messages": [AIMessage(content="response without tools", tool_calls=[])],
        "user_id": "u1",
        "conversation_id": "c1",
        "long_term_memory": "",
        "crisis_triggered": False,
        "agent_type": "knowledge",
    }
    assert should_continue_knowledge(state) == "crisis_check"


def test_should_continue_knowledge_empty_messages_routes_to_crisis_check():
    """当 messages 为空时，不崩溃，应路由到 crisis_check。"""
    from app.agent.graph import should_continue_knowledge

    state = {
        "messages": [],
        "user_id": "u1",
        "conversation_id": "c1",
        "long_term_memory": "",
        "crisis_triggered": False,
        "agent_type": "knowledge",
    }
    assert should_continue_knowledge(state) == "crisis_check"
