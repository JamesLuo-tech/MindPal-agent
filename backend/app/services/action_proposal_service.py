"""Agent 写入提议的服务端持久化 + 确认执行。

设计要点（对应之前的安全审查发现）：
  - 提议在生成时就写进 action_proposals 表，proposal_id 是真实的数据库主键，
    不是内存里现造的 uuid4()
  - 确认接口只接收 proposal_id，action/params 从这张表里取，不信任客户端
    重新传回来的值
  - 确认时校验所有权（user_id 匹配）、状态（必须是 pending）、TTL（没过期）
  - 用 `SELECT ... FOR UPDATE` 加行锁 + 事务，保证并发下同一个 proposal_id
    不会被执行两次——这是幂等性的真正保证，不是靠一个"幂等键"字段本身，
    是靠数据库事务的原子性
  - 重复确认已经 confirmed 的提议不报错，直接返回上一次的执行结果
    （真正的幂等语义：重复调用效果等同于只调用一次，而不是报错）
  - 这张表本身就是审计日志，不用额外再建一张
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import asyncpg

from app.agent.actions import ACTION_DISPATCH

PROPOSAL_TTL_MINUTES = 15


class ProposalNotFoundError(Exception):
    """提议不存在，或者不属于这个用户——两种情况统一报同一个错，
    不向调用方泄露"这个 id 存在但是别人的"这种信息。"""


class ProposalExpiredError(Exception):
    pass


class ProposalAlreadyProcessedError(Exception):
    """提议已经被处理过（expired/cancelled），没法再确认执行。
    注意：status == 'confirmed' 不会走到这个异常——那种情况是幂等地
    返回上次的结果，不是报错。"""

    def __init__(self, status: str):
        self.status = status
        super().__init__(f"该提议已经是 {status} 状态，无法再次确认")


async def create_proposal(
    user_id: UUID,
    conversation_id: UUID | None,
    action: str,
    params: dict,
    summary: str,
    db: asyncpg.Connection,
    ttl_minutes: int = PROPOSAL_TTL_MINUTES,
) -> dict:
    """把一条 Agent 生成的提议真正写进数据库，返回持久化后的记录
    （包含真实的数据库主键 id，前端拿这个 id 去确认）。"""
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
    row = await db.fetchrow(
        """
        INSERT INTO action_proposals (user_id, conversation_id, action, params, summary, expires_at)
        VALUES ($1, $2, $3, $4::jsonb, $5, $6)
        RETURNING id, expires_at
        """,
        # params 直接传字典，不要手动 json.dumps()——asyncpg 的 jsonb 类型编解码器
        # （database.py 的 _init_connection 里注册的）会自动编码，手动再 dumps
        # 一次会把结果变成一个被转义过的 JSON 字符串，读回来的时候就不再是
        # 字典而是字符串，之前项目里踩过这个坑（jsonb 字段双重编码）。
        user_id, conversation_id, action, params, summary, expires_at,
    )
    return {"id": row["id"], "expires_at": row["expires_at"]}


async def confirm_proposal(user_id: UUID, proposal_id: UUID, db: asyncpg.Connection) -> dict:
    """校验所有权/状态/TTL，通过后在一个事务里执行真正的写入并把提议标记
    为已确认。返回 {"action": ..., "result": ...}。

    有个坑记录一下：asyncpg 的事务是"块内抛异常就整体回滚"，如果在
    db.transaction() 块里既执行了一次 UPDATE、又紧接着 raise，那次 UPDATE
    会跟着一起被回滚掉——之前"标记过期"那段代码就是这么写的，mock 测试
    测不出来（mock 不模拟真实的回滚语义），拿真实数据库跑才发现"报了
    ProposalExpiredError，但数据库里状态其实还是 pending"。所以下面把
    "要不要在块外抛异常"这件事，改成用一个标志位记下来，等事务提交完了
    再抛，不会让这次标记过期的 UPDATE 被自己抛的异常回滚掉。
    """
    should_raise_expired = False

    async with db.transaction():
        row = await db.fetchrow(
            """
            SELECT user_id, action, params, summary, status, expires_at, result
            FROM action_proposals
            WHERE id = $1
            FOR UPDATE
            """,
            proposal_id,
        )

        if row is None or str(row["user_id"]) != str(user_id):
            raise ProposalNotFoundError()

        if row["status"] == "confirmed":
            # 幂等：重复确认同一条已经执行过的提议，直接把上次的结果原样
            # 返回，不重新跑一遍 service 层——不然同一个"确认"按钮被点两次
            # （网络重试、手抖连点）会导致同一条记录被写两次。
            return {"action": row["action"], "result": row["result"]}

        if row["status"] in ("expired", "cancelled"):
            raise ProposalAlreadyProcessedError(row["status"])

        if row["expires_at"] < datetime.now(timezone.utc):
            await db.execute(
                "UPDATE action_proposals SET status = 'expired' WHERE id = $1", proposal_id,
            )
            should_raise_expired = True
        else:
            handler = ACTION_DISPATCH.get(row["action"])
            if handler is None:
                raise ValueError(f"未知的 action: {row['action']}")

            result = await handler(user_id, row["params"], db)

            await db.execute(
                """
                UPDATE action_proposals
                SET status = 'confirmed', result = $2::jsonb, confirmed_at = NOW()
                WHERE id = $1
                """,
                proposal_id, result,
            )

    if should_raise_expired:
        raise ProposalExpiredError()

    return {"action": row["action"], "result": result}
