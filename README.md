# MindPal — AI 心理陪伴助手

MindPal 是一个面向年轻人的 AI 心理陪伴应用。它不是冷冰冰的心理咨询机器人，而是一个有网感、懂情绪、像发小一样陪你聊的 AI 朋友。

## 功能特性

- **智能对话** — 基于 LangGraph 构建的多节点 Agent，能感知情绪、调用工具、深度共情
- **长期记忆** — 记住用户的个人信息和过往经历，跨会话持续了解你
- **危机检测** — 自动识别高危关键词，及时推送心理援助热线
- **知识检索 (RAG)** — 遇到具体问题时从知识库查找有用信息
- **情绪日历** — 可视化记录每天的情绪状态
- **周报总结** — 自动生成每周情绪与对话洞察报告
- **语音合成 (TTS)** — 支持将回复转为语音播放

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React + TypeScript + Vite |
| 后端 | FastAPI + Python |
| AI Agent | LangGraph + LangChain |
| LLM | DeepSeek |
| 数据库 | Supabase (PostgreSQL + pgvector) |
| 缓存 | Redis |
| 认证 | Supabase Auth |
| 部署 | Docker Compose |

## 项目结构

```
MindPal-agent/
├── backend/
│   ├── app/
│   │   ├── agent/          # LangGraph Agent 核心（graph、tools、memory、crisis）
│   │   ├── api/            # FastAPI 路由（chat、memory、report、tts）
│   │   ├── services/       # 业务逻辑层
│   │   ├── knowledge/      # RAG 知识库摄入
│   │   └── core/           # 认证、依赖注入
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── pages/          # Chat、EmotionCalendar、WeeklyReport、Login
│       ├── components/     # ChatMessage、ChatInput 等
│       └── hooks/          # useChat、useAuth
├── supabase/               # 数据库迁移文件
├── docker-compose.yml
└── .env.example
```

## 本地运行

### 前置要求

- Docker & Docker Compose
- Node.js 18+
- Python 3.11+

### 1. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填入以下必要配置：

```
SUPABASE_URL=your_supabase_url
SUPABASE_ANON_KEY=your_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
DEEPSEEK_API_KEY=your_deepseek_api_key
```

### 2. 启动后端服务

```bash
docker-compose up -d
```

后端运行在 `http://localhost:8000`，API 文档见 `http://localhost:8000/docs`

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端运行在 `http://localhost:5173`

## Agent 工作流程

```
用户输入
   ↓
agent_node（LLM 推理，决定是否调用工具）
   ↓ 有 tool_calls        ↓ 无 tool_calls
tools_node           crisis_check_node
（执行工具）          （危机关键词检测）
   ↓
返回 agent 继续推理
```

## 环境变量说明

参考 `.env.example` 文件，主要配置项：

| 变量 | 说明 |
|------|------|
| `SUPABASE_URL` | Supabase 项目 URL |
| `SUPABASE_ANON_KEY` | Supabase 匿名密钥 |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase 服务角色密钥 |
| `DEEPSEEK_API_KEY` | DeepSeek LLM API 密钥 |
| `REDIS_URL` | Redis 连接地址 |
