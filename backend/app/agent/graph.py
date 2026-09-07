"""LangGraph Agent 编排核心。

节点：
  router          - 路由节点：危机关键词检测 + LLM 分类，绝大多数消息只分出一个
                    意图段（intent_segments 长度为 1）；只有清楚包含两个独立意图
                    的消息才会被拆成两段
  empathy         - 情绪陪伴节点：无工具，专注共情回应（单意图路径）
  knowledge       - 知识检索节点：绑定 lookup/recall_memory，信息整合回应（单意图路径）
  action          - 写入意图节点：绑定"提议"工具，只生成待确认的提议，不落库（单意图路径）
  tools           - 知识类工具执行节点（lookup / recall_memory）
  action_tools    - 写入类工具执行节点（propose_* 系列，纯生成提议，无副作用）
  run_segment     - 多意图路径专用：处理 intent_segments 里的某一段，内部自带
                    工具调用循环（本地消息列表，不碰共享的 messages），只在
                    intent_segments 长度 >= 2 时才会被 Send 并发调用
  merge           - 多意图路径专用：把 run_segment 各分支的回答合成一条自然回复；
                    只有一段时直接透传，不额外调 LLM
  crisis_check    - 危机关键词扫描，设置 crisis_triggered 标志

边：
  router → empathy | knowledge | action（单意图，由 route_after_router 决定）
          | Send(run_segment) × N（多意图，并发扇出，N 目前最多 2）
  empathy/knowledge/action → crisis_check（单意图路径，同之前）
  knowledge ⇄ tools，action ⇄ action_tools（同之前，单意图路径专用）
  run_segment → merge（多意图路径，所有并发分支收敛于此）
  merge → crisis_check
  crisis_check → END
"""
from __future__ import annotations

import operator
import re
from typing import Annotated, Sequence, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Send

from app.agent.actions import ACTION_TOOLS
from app.agent.crisis import CRITICAL_KEYWORDS
from app.agent.llm import get_llm
from app.agent.prompts import ACTION_PROMPT, EMPATHY_PROMPT, KNOWLEDGE_PROMPT
from app.agent.tools import TOOLS


class IntentSegment(TypedDict):
    agent_type: str  # "empathy" | "knowledge" | "action"
    text: str  # 这一段对应的原文（单意图时就是整句话）


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    user_id: str
    conversation_id: str
    long_term_memory: str
    crisis_triggered: bool
    agent_type: str  # "empathy" | "knowledge" | "action"，由 router_node 写入，单意图路径用
    intent_segments: list[IntentSegment]  # router 拆出来的意图段，绝大多数情况下长度为 1
    segment_responses: Annotated[list[dict], operator.add]  # run_segment 各分支并发累加的回答
    current_segment: IntentSegment  # 只有被 Send 派发到 run_segment 的那次调用才会带这个字段
    self_critique_note: str  # 上一轮反思留下的自我提醒，chat_service 从 Redis 读出来传入，没有就是空字符串


_ROUTER_HISTORY_TURNS = 3  # 只取最近几轮：分类这一步每条用户消息都要过一次，prompt 要小而快
_ROUTER_HISTORY_MSG_MAXLEN = 150  # 单条历史消息截断长度，避免一条很长的倾诉把分类 prompt 撑爆


def _format_router_history(messages: Sequence[BaseMessage]) -> str:
    """取最近几轮对话（不含当前这句），给分类 LLM 判断指代用——
    比如用户说"那个方法有用吗"，只看这一句话，LLM 根本不知道"那个方法"指什么，
    容易误判成 empathy 或者随便哪个标签。带上最近几轮就能大概率解决这类误分类。
    """
    recent = list(messages)[:-1][-_ROUTER_HISTORY_TURNS * 2:]
    if not recent:
        return "（没有更早的历史，这是这轮对话的第一句）"
    lines = []
    for msg in recent:
        role = "用户" if isinstance(msg, HumanMessage) else "AI"
        content = (msg.content or "")[:_ROUTER_HISTORY_MSG_MAXLEN]
        lines.append(f"{role}：{content}")
    return "\n".join(lines)


_ROUTER_MAX_SEGMENTS = 2  # 真实消息很少能干净拆出 3 个独立意图，拆多了合并质量会崩
_SEGMENT_LINE_RE = re.compile(r"^(empathy|knowledge|action)\s*[:：]\s*(.+)$", re.IGNORECASE)


def _parse_router_response(content: str, fallback_text: str) -> list[IntentSegment]:
    """解析分类 LLM 的回复，兼容两种格式：

    1. 单个标签（比如"empathy"）——绝大多数情况，跟这次改动之前的格式完全一样。
    2. 多行"标签: 这段对应的原文"（最多两行）——LLM 判断这句话包含两个独立意图时才会用这种格式。

    识别不出多段格式（包括本来就是单标签、或者输出乱七八糟）时，一律退回单段兜底，
    整句话当一个意图处理——这条兜底路径和这次改动之前的解析逻辑完全一致，保证
    绝大多数（单意图）消息的行为不受这次改动影响。
    """
    lines = [ln.strip() for ln in content.strip().split("\n") if ln.strip()]
    segments: list[IntentSegment] = []
    for line in lines:
        m = _SEGMENT_LINE_RE.match(line)
        if m:
            segments.append({"agent_type": m.group(1).lower(), "text": m.group(2).strip()})
    if len(segments) >= 2:
        return segments[:_ROUTER_MAX_SEGMENTS]

    # 兜底：跟这次改动之前的单标签解析逻辑完全一致
    parts = content.strip().lower().split()
    agent_type = parts[0] if parts else "empathy"
    if agent_type not in ("empathy", "knowledge", "action"):
        agent_type = "empathy"
    return [{"agent_type": agent_type, "text": fallback_text}]


async def router_node(state: AgentState) -> dict:
    """两层路由：危机关键词（同步）→ LLM 分类（empathy/knowledge/action，
    绝大多数情况下只分出一段；清楚包含两个独立意图时才会拆成两段）。
    """
    last_user_msg = ""
    for msg in reversed(list(state["messages"])):
        if isinstance(msg, HumanMessage):
            last_user_msg = msg.content
            break

    # 第一层：危机关键词（无需 LLM，只看当前这句，不需要历史，也不做拆分）
    if any(kw in last_user_msg for kw in CRITICAL_KEYWORDS):
        return {
            "agent_type": "empathy",
            "crisis_triggered": True,
            "intent_segments": [{"agent_type": "empathy", "text": last_user_msg}],
        }

    # 第二层：LLM 分类，带上最近几轮历史帮它判断指代/上下文
    recent_history = _format_router_history(state["messages"])
    prompt = (
        "判断用户最新一句消息属于哪种类型。\n\n"
        "大多数情况下整句话只有一个类型，直接回复一个标签就行：empathy、knowledge 或 action。\n\n"
        "只有当这句话清楚地包含两个独立、都需要被处理的意图时（比如同时在倾诉情绪、"
        "又明确要记录一件事），才按下面的格式拆成两行，每行\"标签: 这部分对应的原文\"，"
        "最多拆两段，拿不准就别拆，当一个整体处理：\n"
        "empathy: ...\n"
        "action: ...\n\n"
        "标签定义：\n"
        "empathy  — 倾诉情绪、寻求理解陪伴\n"
        "knowledge — 明确想知道具体方法或信息\n"
        "action — 想记录一下心情/安排一件小事/标记完成或跳过/记下某方法有没有用/"
        "更新安全计划这类具体的记录类意图。**只要出现\"帮我记一下/存一下/标记一下/"
        "更新一下\"这类明确的记录触发词，就应该判成 action，哪怕这句话里同时带着"
        "\"挺难受的\"\"还不错\"\"不想做了\"这类情绪或评价性的字眼——这些字眼通常只是在"
        "描述要记录的内容本身，不代表用户只是想倾诉，不要被这类字眼带偏误判成 empathy。**\n"
        "举例：\n"
        "\"今天在网上查到一个呼吸法，试了下觉得挺舒服的，帮我记一下\" → action"
        "（\"挺舒服的\"是在描述这个方法的效果，\"帮我记一下\"才是真正的意图）\n"
        "\"早上那件事有点烦，不想做了，帮我标掉\" → action（同理，判断标准是有没有出现记录触发词）\n\n"
        f"最近的对话（帮你判断上下文和指代，比如\"那个方法\"指的是什么）：\n{recent_history}\n\n"
        f"用户最新消息：{last_user_msg}\n\n"
        "回复（单个标签，或最多两行\"标签: 文字\"）："
    )
    response = await get_llm().ainvoke(prompt)
    segments = _parse_router_response(response.content, last_user_msg)

    return {
        "agent_type": segments[0]["agent_type"],  # 单意图路径仍然用这个字段路由
        "crisis_triggered": False,
        "intent_segments": segments,
    }


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


_llm_with_action_tools = None


def _get_llm_with_action_tools():
    global _llm_with_action_tools
    if _llm_with_action_tools is None:
        _llm_with_action_tools = get_llm().bind_tools(ACTION_TOOLS)
    return _llm_with_action_tools


_CRISIS_SAFETY_PLAN_HINT = (
    "\n\n【危机时刻提示】ta 现在的状态被判断为危机时刻。"
    "如果上面的长期信息里有 ta 自己写过的「安全计划」，可以在合适的时候，"
    "用朋友的口吻自然地提一句里面具体的内容（比如「你之前写过……要不要现在试试」），"
    "不要生硬地念条目，也不要一次全说完。如果没有安全计划信息，就正常按第一层接住情绪来回应。"
)


async def empathy_agent_node(state: AgentState) -> dict:
    """情绪陪伴节点：无工具，专注共情回应。"""
    system_content = EMPATHY_PROMPT.format(
        long_term_memory=state.get("long_term_memory") or "（暂无档案）",
        short_term_memory="（已包含在对话历史中）",
        self_critique_note=state.get("self_critique_note") or "（暂无）",
    )
    if state.get("crisis_triggered"):
        system_content += _CRISIS_SAFETY_PLAN_HINT
    response = await _get_empathy_llm().ainvoke(
        [SystemMessage(content=system_content)] + list(state["messages"])
    )
    return {"messages": [response]}


async def knowledge_agent_node(state: AgentState) -> dict:
    """知识检索节点：绑定 lookup 工具，信息整合回应。"""
    system_content = KNOWLEDGE_PROMPT.format(
        long_term_memory=state.get("long_term_memory") or "（暂无档案）",
        short_term_memory="（已包含在对话历史中）",
        self_critique_note=state.get("self_critique_note") or "（暂无）",
    )
    response = await _get_llm_with_tools().ainvoke(
        [SystemMessage(content=system_content)] + list(state["messages"])
    )
    return {"messages": [response]}


async def action_agent_node(state: AgentState) -> dict:
    """写入意图节点：绑定 propose_* 工具，只生成待确认的提议，不碰数据库。"""
    system_content = ACTION_PROMPT.format(
        long_term_memory=state.get("long_term_memory") or "（暂无档案）",
        short_term_memory="（已包含在对话历史中）",
        self_critique_note=state.get("self_critique_note") or "（暂无）",
    )
    response = await _get_llm_with_action_tools().ainvoke(
        [SystemMessage(content=system_content)] + list(state["messages"])
    )
    return {"messages": [response]}


# =====================================================================
# 多意图路径：run_segment（并发处理每一段）+ merge（合成最终回复）
#
# 刻意不复用 empathy/knowledge/action 这三个节点——那三个节点绑定的是
# 共享的 state["messages"]，多个 Send 分支并发写同一个列表，工具调用的
# 中间过程（ToolMessage 等）会跟别的分支交错在一起，没法干净拆出"这一段
# 的最终回答是哪一句"。run_segment 用一份只属于这次调用的本地消息列表
# 跑完整个循环，彻底不碰共享的 messages，跑完才把最终文字写进
# segment_responses 累加，交给 merge 统一处理。
# =====================================================================

_SEGMENT_PROMPTS = {"empathy": EMPATHY_PROMPT, "knowledge": KNOWLEDGE_PROMPT, "action": ACTION_PROMPT}
_SEGMENT_MAX_TOOL_ROUNDS = 3  # 防御性上限，避免工具调用死循环


def _segment_llm(agent_type: str):
    if agent_type == "knowledge":
        return _get_llm_with_tools()
    if agent_type == "action":
        return _get_llm_with_action_tools()
    return _get_empathy_llm()


def _segment_tools_by_name(agent_type: str) -> dict:
    if agent_type == "knowledge":
        return {t.name: t for t in TOOLS}
    if agent_type == "action":
        return {t.name: t for t in ACTION_TOOLS}
    return {}


async def run_segment_node(state: AgentState) -> dict:
    """处理 intent_segments 里的某一段，独立跑完自己的工具调用循环（如果需要），
    结果写进 segment_responses 累加，不直接进 messages。
    """
    segment = state["current_segment"]
    agent_type = segment["agent_type"]

    system_content = _SEGMENT_PROMPTS[agent_type].format(
        long_term_memory=state.get("long_term_memory") or "（暂无档案）",
        short_term_memory="（已包含在对话历史中）",
        self_critique_note=state.get("self_critique_note") or "（暂无）",
    )
    # 本地历史：用真实对话历史做上下文，但把"当前要处理的问题"换成这一段的文字，
    # 而不是整句原话——这样 LLM 既看得到上下文，又只需要回应这一段对应的意图。
    local_messages: list[BaseMessage] = list(state["messages"])[:-1] + [HumanMessage(content=segment["text"])]

    llm = _segment_llm(agent_type)
    tools_by_name = _segment_tools_by_name(agent_type)

    response: AIMessage | None = None
    for _ in range(_SEGMENT_MAX_TOOL_ROUNDS):
        response = await llm.ainvoke([SystemMessage(content=system_content)] + local_messages)
        local_messages.append(response)
        if not (isinstance(response, AIMessage) and response.tool_calls):
            break
        for call in response.tool_calls:
            tool = tools_by_name.get(call["name"])
            if tool is None:
                continue
            tool_message = await tool.ainvoke(call)
            local_messages.append(tool_message)

    final_text = response.content if response is not None else ""
    return {"segment_responses": [{"agent_type": agent_type, "text": final_text}]}


_MERGE_PROMPT = (
    "用户这一句话里包含了不止一个意图，下面是分别针对每个意图生成的回答草稿，"
    "请把它们融合成一条自然、连贯、口语化的回复，像朋友聊天一样，不要用"
    "\"关于第一件事……关于第二件事……\"这种生硬的列点方式，"
    "但也不要因为融合而丢掉或改写草稿里的具体内容：\n\n{drafts}"
)


async def merge_node(state: AgentState) -> dict:
    """把 run_segment 各分支的回答合成一条最终回复。只有一段时（绝大多数情况
    路由到这里都是因为上游误判成了多段，或者未来调整了拆分阈值）直接透传，
    不额外调 LLM——避免多花一次调用去"合并"本来就只有一段的内容。
    """
    responses = state.get("segment_responses") or []
    if len(responses) <= 1:
        text = responses[0]["text"] if responses else ""
        return {"messages": [AIMessage(content=text)]}

    drafts = "\n\n".join(f"[{r['agent_type']}] {r['text']}" for r in responses)
    response = await _get_empathy_llm().ainvoke(_MERGE_PROMPT.format(drafts=drafts))
    return {"messages": [AIMessage(content=response.content)]}


def route_after_router(state: AgentState):
    """router_node 执行后决定去哪——单段（绝大多数情况）走原来的三选一，
    完全复用现有路径，行为和成本跟这次改动之前一致；两段才会用 Send
    并发扇出到 run_segment，多花的那次合并调用只有真正多意图时才会发生。
    """
    segments = state.get("intent_segments") or []
    if len(segments) <= 1:
        return state.get("agent_type", "empathy")
    return [Send("run_segment", {**state, "current_segment": seg}) for seg in segments]


def should_continue_knowledge(state: AgentState) -> str:
    """knowledge_agent_node 执行后，判断是否需要调用工具。"""
    if not state.get("messages"):
        return "crisis_check"
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return "crisis_check"


def should_continue_action(state: AgentState) -> str:
    """action_agent_node 执行后，判断是否需要调用提议工具。"""
    if not state.get("messages"):
        return "crisis_check"
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "action_tools"
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
    graph.add_node("action", action_agent_node)
    graph.add_node("tools", ToolNode(TOOLS))
    graph.add_node("action_tools", ToolNode(ACTION_TOOLS))
    graph.add_node("run_segment", run_segment_node)
    graph.add_node("merge", merge_node)
    graph.add_node("crisis_check", crisis_check_node)

    graph.set_entry_point("router")

    graph.add_conditional_edges(
        "router",
        route_after_router,
        # "run_segment" 只会通过 Send 被派发，不会作为 route_after_router 的
        # 普通字符串返回值出现，这里列进来纯粹是让图结构声明完整、方便可视化。
        {"empathy": "empathy", "knowledge": "knowledge", "action": "action", "run_segment": "run_segment"},
    )

    graph.add_edge("empathy", "crisis_check")

    graph.add_conditional_edges(
        "knowledge",
        should_continue_knowledge,
        {"tools": "tools", "crisis_check": "crisis_check"},
    )
    graph.add_edge("tools", "knowledge")

    graph.add_conditional_edges(
        "action",
        should_continue_action,
        {"action_tools": "action_tools", "crisis_check": "crisis_check"},
    )
    graph.add_edge("action_tools", "action")

    graph.add_edge("run_segment", "merge")
    graph.add_edge("merge", "crisis_check")

    graph.add_edge("crisis_check", END)

    return graph.compile()


_graph = None


async def get_graph():
    """获取编译好的 graph 单例（首次调用时构建）。"""
    global _graph
    if _graph is None:
        _graph = await build_graph()
    return _graph
