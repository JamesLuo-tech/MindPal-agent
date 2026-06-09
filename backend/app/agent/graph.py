"""LangGraph Agent 编排核心。

节点：
  router          - 路由节点：危机关键词检测 + LLM 分类（empathy/knowledge）
  empathy         - 情绪陪伴节点：无工具，专注共情回应
  knowledge       - 知识检索节点：绑定工具，信息整合回应
  tools           - 工具执行节点（lookup / recall_memory）
  crisis_check    - 危机关键词扫描，设置 crisis_triggered 标志

边：
  router → empathy | knowledge（由 route_after_router 决定）
  empathy → crisis_check
  knowledge → tools（有 tool_calls）| crisis_check（无 tool_calls）
  tools → knowledge（工具执行完回到 knowledge 继续推理）
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
from app.agent.prompts import EMPATHY_PROMPT, KNOWLEDGE_PROMPT
from app.agent.tools import TOOLS


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    user_id: str
    conversation_id: str
    long_term_memory: str
    crisis_triggered: bool
    agent_type: str  # "empathy" | "knowledge"，由 router_node 写入


async def router_node(state: AgentState) -> dict:
    """两层路由：危机关键词（同步）→ LLM 分类（empathy/knowledge）。"""
    last_user_msg = ""
    for msg in reversed(list(state["messages"])):
        if isinstance(msg, HumanMessage):
            last_user_msg = msg.content
            break

    # 第一层：危机关键词（无需 LLM）
    if any(kw in last_user_msg for kw in CRITICAL_KEYWORDS):
        return {"agent_type": "empathy", "crisis_triggered": True}

    # 第二层：LLM 分类
    prompt = (
        "判断用户消息属于哪种类型，只回复对应标签：\n\n"
        "empathy  — 倾诉情绪、寻求理解陪伴\n"
        "knowledge — 明确想知道具体方法或信息\n\n"
        f"用户消息：{last_user_msg}\n\n"
        "只回复 empathy 或 knowledge："
    )
    response = await get_llm().ainvoke(prompt)
    parts = response.content.strip().lower().split()
    agent_type = parts[0] if parts else "empathy"
    if agent_type not in ("empathy", "knowledge"):
        agent_type = "empathy"

    return {"agent_type": agent_type, "crisis_triggered": False}


_empathy_llm = None


def _get_empathy_llm():
    global _empathy_llm
    if _empathy_llm is None:
        _empathy_llm = get_llm()
    return _empathy_llm


_llm_with_tools = None


def _get_llm_with_tools():
    global _llm_with_tools
    if _llm_with_tools is None:
        _llm_with_tools = get_llm().bind_tools(TOOLS)
    return _llm_with_tools


async def empathy_agent_node(state: AgentState) -> dict:
    """情绪陪伴节点：无工具，专注共情回应。"""
    system_content = EMPATHY_PROMPT.format(
        long_term_memory=state.get("long_term_memory") or "（暂无档案）",
        short_term_memory="（已包含在对话历史中）",
    )
    response = await _get_empathy_llm().ainvoke(
        [SystemMessage(content=system_content)] + list(state["messages"])
    )
    return {"messages": [response]}


async def knowledge_agent_node(state: AgentState) -> dict:
    """知识检索节点：绑定 lookup 工具，信息整合回应。"""
    system_content = KNOWLEDGE_PROMPT.format(
        long_term_memory=state.get("long_term_memory") or "（暂无档案）",
        short_term_memory="（已包含在对话历史中）",
    )
    response = await _get_llm_with_tools().ainvoke(
        [SystemMessage(content=system_content)] + list(state["messages"])
    )
    return {"messages": [response]}


def route_after_router(state: AgentState) -> str:
    """router_node 执行后，根据 agent_type 决定去哪个 agent。"""
    return state.get("agent_type", "empathy")


def should_continue_knowledge(state: AgentState) -> str:
    """knowledge_agent_node 执行后，判断是否需要调用工具。"""
    if not state.get("messages"):
        return "crisis_check"
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
    """构建并编译多 Agent LangGraph 图。"""
    graph = StateGraph(AgentState)

    graph.add_node("router", router_node)
    graph.add_node("empathy", empathy_agent_node)
    graph.add_node("knowledge", knowledge_agent_node)
    graph.add_node("tools", ToolNode(TOOLS))
    graph.add_node("crisis_check", crisis_check_node)

    graph.set_entry_point("router")

    graph.add_conditional_edges(
        "router",
        route_after_router,
        {"empathy": "empathy", "knowledge": "knowledge"},
    )

    graph.add_edge("empathy", "crisis_check")

    graph.add_conditional_edges(
        "knowledge",
        should_continue_knowledge,
        {"tools": "tools", "crisis_check": "crisis_check"},
    )
    graph.add_edge("tools", "knowledge")
    graph.add_edge("crisis_check", END)

    return graph.compile()


_graph = None


async def get_graph():
    """获取编译好的 graph 单例（首次调用时构建）。"""
    global _graph
    if _graph is None:
        _graph = await build_graph()
    return _graph
