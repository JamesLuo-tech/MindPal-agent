# MindPal — AI 心理陪伴助手

MindPal 是一个面向年轻人的 AI 心理陪伴应用。它不是冷冰冰的心理咨询机器人，而是一个有网感、懂情绪、像发小一样陪你聊的 AI 朋友——聊天之外，还能帮你把心情、小行动、安全计划这些东西真正记下来。

## 功能特性

- **多节点 Agent 编排** — 基于 LangGraph 的路由型 Agent：先判断这句话是想倾诉（empathy）、查信息（knowledge）还是要记录点什么（action），再分发到对应节点；一句话里同时夹着两个意图时（比如"挺难受的，另外帮我记一下心情"），会拆成两段并发处理，再合成一条自然的回复
- **提议-确认写入** — Agent 能记心情、加小行动、标记完成/跳过、约定稍后跟进、记应对方法有没有用、存长期记忆、改安全计划，但 LLM 自己**不能**直接写库——只生成一张待确认的提议卡片，用户点确认后才真正落库，确认接口会用 Pydantic 重新校验一遍参数
- **RAG Fusion 知识检索** — 查询会先被改写成几种不同表达分别检索，再用 RRF（倒数排名融合）重排，缓解口语提问和知识库书面表达之间的措辞落差；本地知识库信心不够时自动 fallback 到实时网络搜索
- **三层记忆** — Redis 短期会话记忆、pgvector 长期语义记忆（定期摘要 + 语义召回）、用户自维护的结构化安全计划
- **危机检测** — 关键词命中时优先于分类判断，直接接住情绪并推送心理援助热线，不经过可能出错的 LLM 分类
- **问诊摘要** — 一键把过去 7/14/30 天记录过的情绪、睡眠、行动完成率整理成几条可信的统计要点（不用 LLM 生成，避免编造），方便带去见医生/咨询师
- **五个功能页** — 今日速记 / 聊聊 / 小步行动 / 变化（情绪日历+趋势+问诊摘要）/ 支持（安全计划+可信联系人）；聊天对匿名用户开放，其余四个需要登录
- **语音合成 (TTS)** — 支持把回复转成语音播放

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 18 + TypeScript + Vite + Tailwind CSS + zustand + react-router |
| 后端 | FastAPI + Python 3.11 + asyncpg |
| AI Agent | LangGraph 0.2 + LangChain 0.3 |
| LLM | DeepSeek（deepseek-chat） |
| Embedding | BGE-M3（sentence-transformers，本地跑） |
| 数据库 | Supabase (PostgreSQL + pgvector)，RLS 按 `auth.uid()` 隔离 |
| 缓存 | Redis（本地开发用 fakeredis 兜底，不强依赖真实 Redis） |
| 认证 | Supabase Auth（支持匿名登录） |
| 实时搜索 | SerpAPI（RAG 本地检索分数不够时的 fallback） |
| 测试 | pytest + pytest-asyncio（后端）、Vitest + React Testing Library（前端） |
| CI | GitHub Actions（前端 tsc + vitest + build，后端 pytest） |

## 项目结构

```
MindPal-agent/
├── backend/
│   ├── app/
│   │   ├── agent/           # LangGraph Agent 核心
│   │   │   ├── graph.py       # 路由 + 多意图拆分/合并 + 各节点
│   │   │   ├── actions.py     # 7 个 propose_* 写入工具 + 确认后执行的 ACTION_DISPATCH
│   │   │   ├── tools.py       # 只读工具：lookup（RAG Fusion）、recall_memory
│   │   │   ├── rag.py         # RAG Fusion + RRF 检索、SerpAPI fallback
│   │   │   ├── memory.py      # 三层记忆读写
│   │   │   ├── crisis.py      # 危机关键词表、热线文案
│   │   │   └── router_eval_cases.json  # 人工标注的路由分类评测集
│   │   ├── api/              # FastAPI 路由：chat / today / goals / support / actions / summary / report / memory / tts
│   │   ├── services/          # 业务逻辑层，路由和 Agent 共用
│   │   ├── schemas/           # Pydantic 数据模型
│   │   └── knowledge/         # RAG 知识库种子数据（24 篇）+ 评测问题集
│   ├── tests/                 # 137 个测试
│   ├── eval_rag.py            # RAGAS 离线评测：RAG 检索质量
│   ├── eval_router.py         # 路由分类离线评测：多采样 + 混淆矩阵
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── pages/            # Chat / Today / SmallSteps / Support / Changes（含日历/趋势/问诊摘要三个子视图）
│       ├── components/       # ActionProposalCard、LoginWidget、Sidebar、MobileTopBar 等
│       ├── layouts/           # AppShell（网页版布局：侧边栏 + 移动端顶栏）
│       ├── lib/                # auth.ts、supabase.ts
│       └── store/             # zustand 状态
├── supabase/migrations/       # 数据库迁移（用户表、5 个功能页数据表、coping_results）
├── .github/workflows/ci.yml
├── docker-compose.yml         # 可选：容器化启动方式
└── .env.example
```

## 本地运行

日常开发直接用本机 Python/Node 跑，不强依赖 Docker（Redis 缺失时会自动切换到 fakeredis 内存模式）。

### 前置要求

- Python 3.11+
- Node.js 18+
- 一个 Supabase 项目（Postgres + pgvector，需要跑 `supabase/migrations/` 里的迁移）
- DeepSeek API Key

### 1. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，至少填好 `SUPABASE_URL` / `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_ROLE_KEY` / `DATABASE_URL` / `DEEPSEEK_API_KEY`；`SERPAPI_KEY` 不填的话 RAG fallback 到网络搜索这条路会跳过，不影响本地知识库检索。

### 2. 启动后端

```bash
cd backend
python -m venv ../.venv && ../.venv/Scripts/activate  # Windows；macOS/Linux 用 source ../.venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

首次启动要加载 BGE-M3 embedding 模型，比较慢，耐心等一下。后端跑在 `http://localhost:8000`，API 文档见 `/docs`。

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev
```
<img width="1483" height="862" alt="image" src="https://github.com/user-attachments/assets/4a6c8a3b-e624-4646-ad79-91bd746e54aa" />

前端跑在 `http://localhost:5173`。

### 也可以用 Docker

```bash
docker-compose up -d
```

## Agent 工作流

```
用户消息
   │
   ▼
router_node ── 危机关键词命中？──是──▶ 直接判 empathy + crisis_triggered=True（跳过 LLM）
   │否
   ▼
LLM 分类（带最近几轮历史，帮它判断"那个方法"这类指代）
   │
   ├─ 单意图（绝大多数情况）──▶ empathy | knowledge | action 三选一
   │                              empathy：纯共情，无工具
   │                              knowledge：绑 lookup / recall_memory，带 ⇄tools 循环
   │                              action：绑 7 个 propose_* 工具，带 ⇄action_tools 循环
   │
   └─ 清楚识别出两个独立意图 ──▶ Send 并发扇出到 run_segment × 2
                                     （各自跑本地工具循环，不碰共享历史）
                                          │
                                          ▼
                                        merge_node（合成一条自然回复；单段时直接透传，不多花一次调用）
   │
   ▼
crisis_check_node（兜底再扫一次关键词）
   │
   ▼
SSE 推给前端：message（逐字流式）/ tool_use / tool_result / action_proposal / done
```

写入这一侧是完全独立的另一条链路：`propose_*` 工具只生成 JSON 提议、不碰数据库；前端弹确认卡片，用户点确认后调用 `/api/chat/actions/confirm`，用 Pydantic 重新校验参数、走 service 层真正执行——LLM 全程没有 SQL 执行权限。

## 测试与评测

```bash
# 后端单测（137 个，mock 掉 LLM，测控制流/解析逻辑）
cd backend && pytest tests/ -v

# 前端单测（47 个）
cd frontend && npm test

# RAG 检索质量离线评测（真实 LLM + RAGAS 指标：faithfulness / answer_relevancy / context_precision / context_recall）
cd backend && python eval_rag.py

# 路由分类离线评测（真实 LLM，人工标注集 + 混淆矩阵，每条用例多采样避免单次结果的随机性）
cd backend && python eval_router.py
```

单测和离线评测是两回事：单测 mock 掉 LLM，测的是代码逻辑对不对（危机词该不该短路、JSON 解析对不对、SSE 过滤该不该转发）；`eval_rag.py`/`eval_router.py` 真调 LLM，测的是"分类/检索准不准"，跑起来会有真实的 API 开销和采样波动。

## 环境变量说明

参考 `.env.example`，主要配置项：

| 变量 | 说明 |
|------|------|
| `SUPABASE_URL` / `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_ROLE_KEY` | Supabase 项目凭据 |
| `DATABASE_URL` | Postgres 直连地址（pgvector 检索用） |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` | DeepSeek LLM API |
| `SERPAPI_KEY` | RAG 本地检索分数不够时的实时搜索 fallback，可选 |
| `REDIS_URL` | 缺失时自动降级为 fakeredis 内存模式，本地开发可以不配 |
| `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` / `VITE_API_BASE_URL` | 前端读取，Vite 约定前缀 `VITE_` |

## 已知限制

- 路由分类目前的真实准确率（三采样评测基线）大约 76%，action 类别是最大的薄弱环节——具体表现和已经试过的修复方向记在 `router_eval_cases.json` 和 `eval_router.py` 里
- 结构化长期记忆表（`user_profiles`/`key_events`）目前没有写入路径，实际记忆能力靠向量记忆和短期会话历史支撑
- Agent 还不会主动读取待办日程去发起跟进提醒（比如"你昨天说要散步的，做了吗"），目前只在用户主动提起时才会用到 `recall_memory`
