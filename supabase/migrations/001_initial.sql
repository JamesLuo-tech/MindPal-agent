-- MindPal 初始数据库 Schema
-- 在 Supabase Dashboard > SQL Editor 中执行

-- 启用必需扩展
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 用户档案 (扩展 auth.users)
CREATE TABLE user_profiles (
    user_id      UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    nickname     VARCHAR(64),
    age_range    VARCHAR(16),
    diagnosis    TEXT,
    preferences  JSONB DEFAULT '{}',
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- 会话
CREATE TABLE conversations (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id      UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    title        VARCHAR(255),
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_conversations_user ON conversations(user_id, created_at DESC);

-- 消息
CREATE TABLE messages (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            VARCHAR(16) NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT NOT NULL,
    used_tools      JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_messages_conv ON messages(conversation_id, created_at);

-- 情绪记录
CREATE TABLE emotions (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id            UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    message_id         UUID REFERENCES messages(id) ON DELETE SET NULL,
    primary_emotion    VARCHAR(32),
    secondary_emotions JSONB DEFAULT '[]',
    intensity          SMALLINT CHECK (intensity BETWEEN 1 AND 10),
    triggers           JSONB DEFAULT '[]',
    created_at         TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_emotions_user_time ON emotions(user_id, created_at DESC);

-- 关键事件
CREATE TABLE key_events (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id      UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    event_type   VARCHAR(32),
    content      TEXT,
    importance   SMALLINT DEFAULT 5 CHECK (importance BETWEEN 1 AND 10),
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_key_events_user ON key_events(user_id);

-- 向量记忆 (对话摘要)
CREATE TABLE memories (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id            UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    summary            TEXT NOT NULL,
    embedding          vector(1024),
    source_message_ids UUID[] DEFAULT '{}',
    created_at         TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_memories_user ON memories(user_id);
CREATE INDEX idx_memories_embedding ON memories
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- 危机事件日志
CREATE TABLE crisis_events (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    message_id      UUID REFERENCES messages(id) ON DELETE SET NULL,
    matched_keyword VARCHAR(64),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- RAG 知识库 (全局共享)
CREATE TABLE knowledge_base (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    topic             VARCHAR(64) NOT NULL,
    title             VARCHAR(255) NOT NULL,
    question_variants JSONB DEFAULT '[]',
    content           TEXT NOT NULL,
    source            VARCHAR(255),
    source_url        TEXT,
    embedding         vector(1024),
    quality_score     REAL DEFAULT 1.0,
    is_active         BOOLEAN DEFAULT TRUE,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_kb_topic ON knowledge_base(topic);
CREATE INDEX idx_kb_embedding ON knowledge_base
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 20);

-- 查询日志 (用于 RAG 迭代)
CREATE TABLE lookup_logs (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id        UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    query          TEXT NOT NULL,
    source         VARCHAR(16) NOT NULL CHECK (source IN ('rag', 'web')),
    rag_top_score  REAL,
    hit_kb_id      UUID REFERENCES knowledge_base(id) ON DELETE SET NULL,
    created_at     TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_lookup_logs_source ON lookup_logs(source, created_at DESC);

-- =====================
-- Row Level Security
-- =====================

ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE emotions ENABLE ROW LEVEL SECURITY;
ALTER TABLE key_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE crisis_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_base ENABLE ROW LEVEL SECURITY;

CREATE POLICY "own_profile" ON user_profiles FOR ALL
    USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

CREATE POLICY "own_conversations" ON conversations FOR ALL
    USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

CREATE POLICY "own_messages" ON messages FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM conversations c
            WHERE c.id = messages.conversation_id AND c.user_id = auth.uid()
        )
    );

CREATE POLICY "own_emotions" ON emotions FOR ALL
    USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

CREATE POLICY "own_key_events" ON key_events FOR ALL
    USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

CREATE POLICY "own_memories" ON memories FOR ALL
    USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

CREATE POLICY "own_crisis_events" ON crisis_events FOR ALL
    USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

CREATE POLICY "kb_read_authenticated" ON knowledge_base FOR SELECT
    TO authenticated USING (is_active = TRUE);
