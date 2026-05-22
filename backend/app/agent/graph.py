"""LangGraph Agent 编排核心。

节点：
  agent_node      - LLM 推理，决定是否调用工具
  tools_node      - 工具执行（lookup / recall_memory）
  crisis_check    - 危机关键词扫描，设置 crisis_triggered 标志

边：
  agent → tools（有 tool_calls）| crisis_check（无 tool_calls）
  tools → agent（工具执行完回到 agent 继续推理）
  crisis_check → END
"""
from __future__ import annotations

import operator
from typing import Annotated, Sequence, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from app.agent.crisis import CRITICAL_KEYWORDS
from app.agent.llm import get_llm
from app.agent.prompts import SYSTEM_PROMPT_TEMPLATE
from app.agent.tools import TOOLS


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    user_id: str
    conversation_id: str
    long_term_memory: str
    crisis_triggered: bool


_llm_with_tools = None


def _get_llm_with_tools():
    global _llm_with_tools
    if _llm_with_tools is None:
        _llm_with_tools = get_llm().bind_tools(TOOLS)
    return _llm_with_tools


async def agent_node(state: AgentState) -> dict:
    """LLM 推理节点：构建系统提示，调用 LLM（含工具绑定），返回 AI 消息。"""
    system_content = SYSTEM_PROMPT_TEMPLATE.format(
        long_term_memory=state.get("long_term_memory") or "（暂无档案）",
        short_term_memory="（已包含在对话历史中）",
    )
    response = await _get_llm_with_tools().ainvoke(
        [SystemMessage(content=system_content)] + list(state["messages"])
    )
    return {"messages": [response]}


def should_continue(state: AgentState) -> str:
    """根据最后一条 AI 消息判断下一节点。"""
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return "crisis_check"


async def crisis_check_node(state: AgentState) -> dict:
    """扫描最近的用户消息，若含危机关键词则设置 crisis_triggered 标志。

    实际热线文字的追加由 chat_service 在流式输出后处理，
    这里只负责检测并打标，保持图节点的职责单一。
    """
    user_content = ""
    for msg in reversed(list(state["messages"])):
        if isinstance(msg, HumanMessage):
            user_content = msg.content
            break

    triggered = any(kw in user_content for kw in CRITICAL_KEYWORDS)
    return {"crisis_triggered": triggered}


async def build_graph():
    """构建并编译 LangGraph 图。"""
    graph = StateGraph(AgentState)

    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(TOOLS))
    graph.add_node("crisis_check", crisis_check_node)

    graph.set_entry_point("agent")

    graph.add_conditional_edges(
        "agent",
        should_continue,
        {"tools": "tools", "crisis_check": "crisis_check"},
    )
    graph.add_edge("tools", "agent")
    graph.add_edge("crisis_check", END)

    return graph.compile()


_graph = None


async def get_graph():
    """获取编译好的 graph 单例（首次调用时构建）。"""
    global _graph
    if _graph is None:
        _graph = await build_graph()
    return _graph
