# Multi-Agent 架构设计

**日期：** 2026-06-08
**状态：** 已批准

---

## 背景

当前 MindPal 是单 Agent ReAct 架构，一个 LLM 节点同时负责情绪陪伴和知识检索，行为边界模糊。改造为多 Agent 架构，让不同场景由专职 Agent 处理。

---

## 架构

```
每条用户消息
       ↓
  router_node
  ├─ 危机关键词命中 → crisis_triggered=True + agent_type="empathy"
  │                   ↓
  ├─ LLM 判断 "empathy" ──→ empathy_agent_node → crisis_check_node → END
  │                          （无工具，情绪陪伴；危机时热线由 chat_service 追加）
  └─ LLM 判断 "knowledge" → knowledge_agent_node → tools_node → knowledge_agent_node → crisis_check_node → END
                             （有 lookup 工具，信息整合）
```

---

## Router Node

**两层路由，按优先级：**

1. **危机关键词（同步）** — 复用 `CRITICAL_KEYWORDS`，命中即设 `crisis_triggered=True` + `agent_type="empathy"`，跳过 LLM（危机需要情绪陪伴，热线由 chat_service 追加）
2. **LLM 分类** — 极短 prompt，只分析最后一条用户消息，输出 `empathy` 或 `knowledge`

**分类 prompt：**
```
判断用户消息属于哪种类型，只回复对应标签：
empathy  — 倾诉情绪、寻求理解陪伴
knowledge — 明确想知道具体方法或信息
用户消息：{message}
只回复 empathy 或 knowledge：
```

**默认值：** 解析失败时默认 `empathy`（宁可多陪伴，少误判）

---

## Agent 节点

### Empathy Agent
- **工具：** 无
- **Prompt：** 复用现有 `SYSTEM_PROMPT_TEMPLATE`
- **风格：** 短句微信风格，情绪优先，3-4 句

### Knowledge Agent
- **工具：** `lookup`（RAG Fusion + SerpAPI fallback）
- **Prompt：** 新写，信息优先，朋友口吻讲出来，结尾追问有没有帮助
- **风格：** 稍正式，不超过 3 个要点

---

## 状态变更

`AgentState` 新增字段：

```python
agent_type: str  # "empathy" | "knowledge"，router 写入
```

---

## Crisis 处理

保持现有逻辑不变：`chat_service.py` 里的 `check_and_append_hotline` 在流式输出后追加热线。`crisis_check_node` 只负责打标记。

---

## 文件改动范围

| 文件 | 改动 |
|------|------|
| `agent/graph.py` | 加 `router_node`，拆分 `agent_node` 为 `empathy_agent_node` / `knowledge_agent_node`，更新条件边 |
| `agent/prompts.py` | 拆分为 `ROUTER_PROMPT` / `EMPATHY_PROMPT`（现有）/ `KNOWLEDGE_PROMPT`（新增） |
| `agent/tools.py` | 不变 |
| `agent/memory.py` | 不变 |
| `services/chat_service.py` | 不变 |
| `api/chat.py` | 不变 |

---

## 延迟影响

Router 多一次 LLM 调用，但 prompt 极短，DeepSeek 预计响应 300ms 内。对用户感知影响轻微。

---

## 前端影响

无。Agent 切换完全在后端发生，前端无需修改。
