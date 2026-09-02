-- MindPal 5-Tab 改版 Schema
-- 新增：今日速记 / 小步行动日程 / 安全计划 / 可信联系人

-- 今日速记（用户主动自评，跟聊天时 LLM 自动提取的 emotions 表分开）
CREATE TABLE daily_checkins (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id       UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    checkin_date  DATE NOT NULL DEFAULT CURRENT_DATE,
    mood          SMALLINT CHECK (mood BETWEEN 1 AND 5),
    energy        SMALLINT CHECK (energy BETWEEN 1 AND 5),
    sleep_hours   NUMERIC(3,1) CHECK (sleep_hours >= 0 AND sleep_hours <= 24),
    small_win     TEXT,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, checkin_date)
);
CREATE INDEX idx_daily_checkins_user_date ON daily_checkins(user_id, checkin_date DESC);

-- 小步行动 / 日程（也是"今日"的下一个日程、"变化"的活动趋势数据源）
CREATE TABLE schedule_items (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id        UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    title          VARCHAR(120) NOT NULL,
    category       VARCHAR(32),
    scheduled_at   TIMESTAMPTZ,
    status         VARCHAR(16) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done', 'skipped')),
    completed_at   TIMESTAMPTZ,
    created_at     TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_schedule_items_user_time ON schedule_items(user_id, scheduled_at);
CREATE INDEX idx_schedule_items_user_status ON schedule_items(user_id, status, created_at DESC);

-- 安全计划（每用户一行）
CREATE TABLE safety_plans (
    user_id                    UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    warning_signs              TEXT,
    internal_coping            TEXT,
    distraction_people_places  TEXT,
    help_contacts               TEXT,
    professional_contacts      TEXT,
    safe_environment            TEXT,
    updated_at                 TIMESTAMPTZ DEFAULT NOW()
);

-- 可信联系人（每用户多行）
-- 字段刻意精简到前端实际用到的：name/relationship/phone。
-- 备注/排序等前端还没有 UI 的字段暂不加，避免死列，需要时再加迁移。
CREATE TABLE trusted_contacts (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id       UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    name          VARCHAR(64) NOT NULL,
    relationship  VARCHAR(32),
    phone         VARCHAR(32),
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_trusted_contacts_user ON trusted_contacts(user_id, created_at);

-- =====================
-- Row Level Security
-- =====================

ALTER TABLE daily_checkins ENABLE ROW LEVEL SECURITY;
ALTER TABLE schedule_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE safety_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE trusted_contacts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "own_daily_checkins" ON daily_checkins FOR ALL
    USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

CREATE POLICY "own_schedule_items" ON schedule_items FOR ALL
    USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

CREATE POLICY "own_safety_plan" ON safety_plans FOR ALL
    USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

CREATE POLICY "own_trusted_contacts" ON trusted_contacts FOR ALL
    USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
