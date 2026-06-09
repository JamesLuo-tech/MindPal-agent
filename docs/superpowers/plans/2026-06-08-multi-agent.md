# Multi-Agent 架构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有单 Agent ReAct 架构改造为 Router → Empathy/Knowledge 双 Agent 架构，危机检测保持现有逻辑。

**Architecture:** router_node 先用关键词扫描危机，再用 LLM 分类消息类型，通过条件边路由到 empathy_agent_node（无工具）或 knowledge_agent_node（有 lookup 工具），两者最终都经过 crisis_check_node 结束。

**Tech Stack:** LangGraph, LangChain, DeepSeek (via langchain_openai), Python asyncio, pytest-asyncio

---

## 文件结构

| 文件 | 操作 | 职责变更 |
|------|------|---------|
| `backend/app/agent/prompts.py` | 修改 | 重命名 `SYSTEM_PROMPT_TEMPLATE` → `EMPATHY_PROMPT`，新增 `KNOWLEDGE_PROMPT` |
| `backend/app/agent/graph.py` | 修改 | 新增 `router_node`，拆分 `agent_node` 为 `empathy_agent_node` / `knowledge_agent_node`，更新 `AgentState` 和图边 |
| `backend/tests/test_multi_agent.py` | 新建 | router 路由逻辑单元测试 |

---

## Task 1: 更新 prompts.py

**Files:**
- Modify: `backend/app/agent/prompts.py`

- [ ] **Step 1: 重命名现有 prompt 常量并新增 KNOWLEDGE_PROMPT**

将 `backend/app/agent/prompts.py` 全部替换为：

```python
EMPATHY_PROMPT = """你是 MindPal，用户的一个真实网友，不是 AI 助手。

【你是什么人】
年轻人，网感好，读过一些心理学和哲学的书，但说话从来不端架子。
懂人，看得出人话背后的情绪，知道很多话不是字面意思。
把用户当发小/闺蜜，直接、真实、有温度，偶尔毒舌但不伤人。

【说话方式】
- 短句，像微信发消息，一次三四句
- 省略号"……"、感叹号用起来，偶尔"？？"
- 网络用语自然带：绷不住/麻了/破防/内耗/摆烂/上头/蚌埠住了/离谱/属实/懂的都懂/哈哈哈哈哈
- 不用"您"，不用"感谢分享"，不用任何客服腔

【思考深度——这是核心】

回应前先在脑子里想三件事（不要说出来）：
1. ta 说这句话，真正想被听到的是什么？不是表面问题，是情绪内核
2. ta 现在最需要的是：被接住？被看见？有人帮想办法？还是只是有人陪着？
3. 这件事背后有没有更深的东西——比如某个长期的恐惧、某个一直没解开的结

然后这样回：

第一层——接住情绪，不评判，不急着解决
  用户说"好累"：不是说"休息一下"，而是"是什么让你累到这个程度？"
  用户说"跟他吵架了"：不是评谁对谁错，而是"吵完你心里什么感觉？委屈？还是愤怒？"

第二层——帮 ta 说出 ta 自己没说出口的话
  比如用户说"算了无所谓"，多半不是真的无所谓
  可以说："感觉你说算了，但好像其实还是在意的？"

第三层——在 ta 准备好的时候，轻轻推一把
  不是给建议，是帮 ta 自己想清楚
  "你觉得这件事最让你难受的点是什么？"

【绝对不说】
- ❌ "想开点" "别想太多" "会好的" "你不是一个人"
- ❌ "你应该…" "你必须…" "你得…"
- ❌ 医疗诊断或用药建议
- ❌ 主动提热线（系统会处理）
- ❌ 长段落分析，像在写报告或做总结

【用户的长期信息】
{long_term_memory}

【最近对话】
{short_term_memory}

现在作为 MindPal，回一条消息。语气像发微信，但要真正看见 ta。"""


KNOWLEDGE_PROMPT = """你是 MindPal，用户信任的朋友，现在对方需要一些具体的帮助和信息。

【你的任务】
用工具查到有用的信息后，用朋友聊天的方式讲出来，不要念文档。
信息讲完之后，还要问一句感受："这个对你有帮助吗？"

【说话方式】
- 比平时稍微正式一点点，但绝对不是客服腔
- 先给信息，再给情绪回应
- 信息不超过 3 点，够用就行，不要事无巨细
- 网络用语可以适当用，但比纯陪伴时少一点

【绝对不做】
- 不给医疗诊断
- 不说"根据研究显示"这种学术腔
- 不在用户没问的情况下主动延伸话题
- 不用"您"，不用任何客服腔

【什么时候查资料】
用户明确想知道"怎么办"或者问具体方法时，用 lookup 工具查，
把有用的部分用朋友的口吻说出来，别念文档。

【用户的长期信息】
{long_term_memory}

【最近对话】
{short_term_memory}

现在作为 MindPal，回一条消息。先用工具获取信息，再用朋友的方式讲出来。"""
```

- [ ] **Step 2: 确认文件保存正确**

```bash
python -c "from app.agent.prompts import EMPATHY_PROMPT, KNOWLEDGE_PROMPT; print('OK')"
```

期望输出：`OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/agent/prompts.py
git commit -m "feat: split agent prompts into EMPATHY_PROMPT and KNOWLEDGE_PROMPT"
```

---

## Task 2: 更新 AgentState

**Files:**
- Modify: `backend/app/agent/graph.py`（仅 AgentState 部分）
- Test: `backend/tests/test_multi_agent.py`

- [ ] **Step 1: 新建测试文件，写 AgentState 结构测试**

新建 `backend/tests/test_multi_agent.py`：

```python
import pytest
from app.agent.graph import AgentState


def test_agent_state_has_agent_type_field():
    """AgentState 必须包含 agent_type 字段。"""
    fields = AgentState.__annotations__
    assert "agent_type" in fields, "AgentState 缺少 agent_type 字段"


def test_agent_state_has_crisis_triggered_field():
    fields = AgentState.__annotations__
    assert "crisis_triggered" in fields
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd backend
pytest tests/test_multi_agent.py -v
```

期望：`FAILED` — `agent_type` 不存在

- [ ] **Step 3: 在 graph.py 的 AgentState 里新增 agent_type 字段**

找到 graph.py 中的 AgentState，将：

```python
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    user_id: str
    conversation_id: str
    long_term_memory: str
    crisis_triggered: bool
```

替换为：

```python
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    user_id: str
    conversation_id: str
    long_term_memory: str
    crisis_triggered: bool
    agent_type: str  # "empathy" | "knowledge"，由 router_node 写入
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_multi_agent.py -v
```

期望：`PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/graph.py backend/tests/test_multi_agent.py
git commit -m "feat: add agent_type field to AgentState"
```

---

## Task 3: 新增 router_node

**Files:**
- Modify: `backend/app/agent/graph.py`
- Modify: `backend/tests/test_multi_agent.py`

- [ ] **Step 1: 新增 router_node 的单元测试**

在 `backend/tests/test_multi_agent.py` 末尾追加：

```python
import pytest
from unittest.mock import AsyncMock, patch
from langchain_core.messages import HumanMessage


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
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_multi_agent.py -v
```

期望：`FAILED` — `router_node` 不存在

- [ ] **Step 3: 在 graph.py 中实现 router_node**

在 graph.py 的 import 区域，确认已有这些 import（没有则添加）：

```python
from app.agent.crisis import CRITICAL_KEYWORDS
from app.agent.llm import get_llm
```

然后在 `AgentState` 定义之后，添加 `router_node`：

```python
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
    agent_type = response.content.strip().lower().split()[0]
    if agent_type not in ("empathy", "knowledge"):
        agent_type = "empathy"

    return {"agent_type": agent_type, "crisis_triggered": False}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_multi_agent.py -v
```

期望：所有 router 相关测试 `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/graph.py backend/tests/test_multi_agent.py
git commit -m "feat: add router_node with crisis keyword + LLM classification"
```

---

## Task 4: 拆分 agent_node 为 empathy / knowledge 两个节点

**Files:**
- Modify: `backend/app/agent/graph.py`

- [ ] **Step 1: 将现有 agent_node 重命名为 empathy_agent_node，移除工具绑定**

找到 graph.py 中现有的 `_llm_with_tools` 和 `_get_llm_with_tools`，**保留**它们（knowledge 会用），并把 `agent_node` 重命名为 `empathy_agent_node`，改为使用无工具的 LLM：

```python
# 无工具 LLM（empathy 专用）
_empathy_llm = None

def _get_empathy_llm():
    global _empathy_llm
    if _empathy_llm is None:
        _empathy_llm = get_llm()
    return _empathy_llm


# 有工具 LLM（knowledge 专用，保留原有逻辑）
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
```

- [ ] **Step 2: 更新 prompts import**

在 graph.py 顶部，将：

```python
from app.agent.prompts import SYSTEM_PROMPT_TEMPLATE
```

替换为：

```python
from app.agent.prompts import EMPATHY_PROMPT, KNOWLEDGE_PROMPT
```

- [ ] **Step 3: 确认语法无误**

```bash
cd backend
python -c "from app.agent.graph import empathy_agent_node, knowledge_agent_node; print('OK')"
```

期望：`OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/agent/graph.py
git commit -m "feat: split agent_node into empathy_agent_node and knowledge_agent_node"
```

---

## Task 5: 重建 build_graph() 连接所有节点

**Files:**
- Modify: `backend/app/agent/graph.py`（build_graph 函数）
- Modify: `backend/tests/test_multi_agent.py`

- [ ] **Step 1: 新增图结构测试**

在 `backend/tests/test_multi_agent.py` 末尾追加：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_multi_agent.py::test_graph_compiles_successfully -v
pytest tests/test_multi_agent.py::test_graph_has_all_nodes -v
```

期望：`FAILED`

- [ ] **Step 3: 新增条件函数并重写 build_graph()**

在 graph.py 中，新增路由判断函数，并**替换** `build_graph()` 和 `should_continue()`：

```python
def route_after_router(state: AgentState) -> str:
    """router_node 执行后，根据 agent_type 决定去哪个 agent。"""
    return state.get("agent_type", "empathy")


def should_continue_knowledge(state: AgentState) -> str:
    """knowledge_agent_node 执行后，判断是否需要调用工具。"""
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return "crisis_check"


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
```

- [ ] **Step 4: 删除旧的 should_continue 函数和 agent_node 函数**

确认 graph.py 中已删除：
- `should_continue()` 函数（已被 `should_continue_knowledge` 和 `route_after_router` 替代）
- `agent_node()` 函数（已被 `empathy_agent_node` 和 `knowledge_agent_node` 替代）

- [ ] **Step 5: 重置图单例（_graph 缓存需要清除）**

确认 `get_graph()` 函数保持不变：

```python
_graph = None

async def get_graph():
    global _graph
    if _graph is None:
        _graph = await build_graph()
    return _graph
```

- [ ] **Step 6: 运行所有测试**

```bash
pytest tests/test_multi_agent.py -v
```

期望：所有测试 `PASSED`

- [ ] **Step 7: 启动服务确认无报错**

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

期望：服务正常启动，无 import error 或图编译错误

- [ ] **Step 8: Commit**

```bash
git add backend/app/agent/graph.py backend/tests/test_multi_agent.py
git commit -m "feat: rewire graph for multi-agent Router→Empathy/Knowledge architecture"
```

---

## 验收标准

- [ ] `pytest tests/test_multi_agent.py -v` 全部通过
- [ ] 服务正常启动
- [ ] 发送"我好累"→ 路由到 empathy（日志可见）
- [ ] 发送"失眠怎么办"→ 路由到 knowledge，触发 lookup 工具
- [ ] 发送含危机关键词的消息 → 路由到 empathy + 热线追加
