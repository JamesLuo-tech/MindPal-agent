-- action_proposals：Agent 生成的"待确认写入提议"在服务端的真实落地。
--
-- 之前 proposal_id 只是流式返回时现造的一个 uuid4()，从没进过数据库，
-- 前端确认时直接把 action/params 原样传回来，服务端对"这是不是真的来自
-- 一次提议"没有任何校验——这张表 + 对应的确认逻辑补上这一层：
--   - 所有权：confirm 时校验 user_id 匹配
--   - 状态机：pending -> confirmed / expired / cancelled，同一条不会被
--     重复执行（幂等：重复确认已 confirmed 的提议直接返回上次的结果）
--   - TTL：过期的提议拒绝确认
--   - 审计：谁在什么时候提议了什么、什么时候确认的、执行结果是什么，
--     这张表本身就是完整的审计记录

CREATE TABLE action_proposals (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
    action          VARCHAR(64) NOT NULL,
    params          JSONB NOT NULL,
    summary         TEXT NOT NULL,
    status          VARCHAR(16) NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'confirmed', 'expired', 'cancelled')),
    result          JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,
    confirmed_at    TIMESTAMPTZ
);

CREATE INDEX idx_action_proposals_user ON action_proposals(user_id, created_at DESC);

ALTER TABLE action_proposals ENABLE ROW LEVEL SECURITY;

CREATE POLICY "own_action_proposals" ON action_proposals
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
