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
