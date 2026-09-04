"""action 路由分类接入 graph 之后的回归测试：确认新节点/新边没有破坏图的完整性，
router 的三分类逻辑对，should_continue_action 的判断逻辑对。"""
import pytest
from unittest.mock import AsyncMock, patch
from langchain_core.messages import AIMessage, HumanMessage


@pytest.mark.asyncio
async def test_graph_compiles_with_action_nodes():
    from app.agent.graph import build_graph
    graph = await build_graph()
    node_names = set(graph.nodes.keys())
    for expected in ("router", "empathy", "knowledge", "action", "tools", "action_tools", "crisis_check"):
        assert expected in node_names, f"缺少节点: {expected}"


@pytest.mark.asyncio
async def test_router_routes_to_action_when_llm_says_action():
    from app.agent.graph import router_node

    mock_response = AsyncMock()
    mock_response.content = "action"
    state = {
        "messages": [HumanMessage(content="帮我记一下今天有点累")],
        "user_id": "u1", "conversation_id": "c1",
        "long_term_memory": "", "crisis_triggered": False, "agent_type": "",
    }
    with patch("app.agent.graph.get_llm") as mock_get_llm:
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_get_llm.return_value = mock_llm
        result = await router_node(state)

    assert result["agent_type"] == "action"
    assert result["crisis_triggered"] is False


@pytest.mark.asyncio
async def test_router_crisis_keyword_still_wins_over_action_classification():
    """危机关键词命中时必须直接走 empathy，不会因为提到"记一下"之类的词被分去 action。"""
    from app.agent.graph import router_node

    state = {
        "messages": [HumanMessage(content="我不想活了，帮我记一下")],
        "user_id": "u1", "conversation_id": "c1",
        "long_term_memory": "", "crisis_triggered": False, "agent_type": "",
    }
    result = await router_node(state)
    assert result["agent_type"] == "empathy"
    assert result["crisis_triggered"] is True


def test_should_continue_action_routes_to_action_tools_when_tool_calls():
    from app.agent.graph import should_continue_action

    state = {
        "messages": [AIMessage(content="", tool_calls=[
            {"id": "1", "name": "propose_create_micro_action", "args": {"title": "散步"}, "type": "tool_call"},
        ])],
        "user_id": "u1", "conversation_id": "c1",
        "long_term_memory": "", "crisis_triggered": False, "agent_type": "action",
    }
    assert should_continue_action(state) == "action_tools"


def test_should_continue_action_routes_to_crisis_check_without_tool_calls():
    from app.agent.graph import should_continue_action

    state = {
        "messages": [AIMessage(content="好呀，那你想先做点什么", tool_calls=[])],
        "user_id": "u1", "conversation_id": "c1",
        "long_term_memory": "", "crisis_triggered": False, "agent_type": "action",
    }
    assert should_continue_action(state) == "crisis_check"


def test_should_continue_action_empty_messages_routes_to_crisis_check():
    from app.agent.graph import should_continue_action

    state = {
        "messages": [], "user_id": "u1", "conversation_id": "c1",
        "long_term_memory": "", "crisis_triggered": False, "agent_type": "action",
    }
    assert should_continue_action(state) == "crisis_check"
