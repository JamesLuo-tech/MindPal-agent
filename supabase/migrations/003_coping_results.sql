-- 记录某个应对方法这次有没有用——喂给"多次验证有效的方法 → 经用户确认进入长期记忆"这条闭环
CREATE TABLE coping_results (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    method      TEXT NOT NULL,
    helped      BOOLEAN,
    note        TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_coping_results_user ON coping_results(user_id, created_at DESC);

ALTER TABLE coping_results ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own_coping_results" ON coping_results FOR ALL
    USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
