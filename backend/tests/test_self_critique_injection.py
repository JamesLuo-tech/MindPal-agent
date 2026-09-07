"""验证 self_critique_note 真的被塞进了各个回答节点发给 LLM 的 prompt 里，
不是只加了字段却没接上——这类"字段加了但没人读"的接线错误，光看代码
容易漏掉，必须直接断言发给 LLM 的内容里有没有这段文字。"""
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage


def _mock_response(content: str = "回复内容", tool_calls: list | None = None):
    msg = AIMessage(content=content, tool_calls=tool_calls or [])
    return msg


@pytest.mark.asyncio
async def test_empathy_node_includes_self_critique_note_in_prompt():
    from app.agent.graph import empathy_agent_node

    state = {
        "messages": [HumanMessage(content="我今天很难受")],
        "long_term_memory": "",
        "crisis_triggered": False,
        "self_critique_note": "上次语气有点说教，这次要多共情少建议",
    }
    with patch("app.agent.graph._get_empathy_llm") as mock_get_llm:
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=_mock_response())
        mock_get_llm.return_value = mock_llm
        await empathy_agent_node(state)

    sent_messages = mock_llm.ainvoke.call_args[0][0]
    system_content = sent_messages[0].content
    assert "上次语气有点说教，这次要多共情少建议" in system_content


@pytest.mark.asyncio
async def test_empathy_node_defaults_placeholder_when_no_note():
    from app.agent.graph import empathy_agent_node

    state = {
        "messages": [HumanMessage(content="你好")],
        "long_term_memory": "",
        "crisis_triggered": False,
        "self_critique_note": "",
    }
    with patch("app.agent.graph._get_empathy_llm") as mock_get_llm:
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=_mock_response())
        mock_get_llm.return_value = mock_llm
        await empathy_agent_node(state)

    system_content = mock_llm.ainvoke.call_args[0][0][0].content
    assert "（暂无）" in system_content


@pytest.mark.asyncio
async def test_knowledge_node_includes_self_critique_note_in_prompt():
    from app.agent.graph import knowledge_agent_node

    state = {
        "messages": [HumanMessage(content="失眠怎么办")],
        "long_term_memory": "",
        "self_critique_note": "上次漏掉了知识意图那部分",
    }
    with patch("app.agent.graph._get_llm_with_tools") as mock_get_llm:
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=_mock_response())
        mock_get_llm.return_value = mock_llm
        await knowledge_agent_node(state)

    system_content = mock_llm.ainvoke.call_args[0][0][0].content
    assert "上次漏掉了知识意图那部分" in system_content


@pytest.mark.asyncio
async def test_action_node_includes_self_critique_note_in_prompt():
    from app.agent.graph import action_agent_node

    state = {
        "messages": [HumanMessage(content="帮我记一下心情")],
        "long_term_memory": "",
        "self_critique_note": "上次说了已经保存，其实还没确认",
    }
    with patch("app.agent.graph._get_llm_with_action_tools") as mock_get_llm:
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=_mock_response())
        mock_get_llm.return_value = mock_llm
        await action_agent_node(state)

    system_content = mock_llm.ainvoke.call_args[0][0][0].content
    assert "上次说了已经保存，其实还没确认" in system_content


@pytest.mark.asyncio
async def test_run_segment_node_includes_self_critique_note_in_prompt():
    from app.agent.graph import run_segment_node

    state = {
        "messages": [HumanMessage(content="我难受，帮我记一下心情")],
        "long_term_memory": "",
        "self_critique_note": "上次合并回复漏了记录那部分",
        "current_segment": {"agent_type": "empathy", "text": "我难受"},
    }
    with patch("app.agent.graph._segment_llm") as mock_segment_llm:
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=_mock_response())
        mock_segment_llm.return_value = mock_llm
        await run_segment_node(state)

    system_content = mock_llm.ainvoke.call_args[0][0][0].content
    assert "上次合并回复漏了记录那部分" in system_content
