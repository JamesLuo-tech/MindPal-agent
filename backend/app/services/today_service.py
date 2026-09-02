"""今日速记服务：今日快照（含 Redis 缓存的个性化推荐）+ 打卡 upsert。"""
from __future__ import annotations

from datetime import date
from uuid import UUID

import asyncpg
import redis.asyncio as aioredis
from langchain_core.messages import HumanMessage

import app.database as _db
from app.agent.llm import get_llm
from app.agent.memory import load_long_term, search_memories
from app.schemas.goals import ScheduleItemOut
from app.schemas.today import CheckinUpsert, DailyCheckinOut, TodaySnapshotOut

RECOMMENDATION_TTL = 6 * 3600  # 6h，避免每次刷新"今日"都触发一次 LLM 调用
_FALLBACK_RECOMMENDATION = "今天也要对自己温柔一点。"

_RECO_PROMPT = """\
以下是一位用户今天的自我记录和你对 ta 的了解，请用温和朋友的口吻，
给一句简短的、贴合 ta 今天状态的关心或小建议（不超过 60 字）。
不要说教，不要"你应该"，就像朋友随口说一句关心的话。
只输出这句话本身，不要加任何前缀。

{context}"""


def _row_to_checkin(row: asyncpg.Record) -> DailyCheckinOut:
    return DailyCheckinOut(
        id=row["id"],
        checkin_date=row["checkin_date"],
        mood=row["mood"],
        energy=row["energy"],
        sleep_hours=float(row["sleep_hours"]) if row["sleep_hours"] is not None else None,
        small_win=row["small_win"],
        created_at=row["created_at"],
    )


async def _fetch_checkin(user_id: UUID, db: asyncpg.Connection) -> DailyCheckinOut | None:
    row = await db.fetchrow(
        """
        SELECT id, checkin_date, mood, energy, sleep_hours, small_win, created_at
        FROM daily_checkins
        WHERE user_id = $1 AND checkin_date = CURRENT_DATE
        """,
        user_id,
    )
    return _row_to_checkin(row) if row else None


async def _fetch_next_schedule_item(user_id: UUID, db: asyncpg.Connection) -> ScheduleItemOut | None:
    """优先取最近定了时间的待办，没有的话取最早创建的待办箱条目。"""
    row = await db.fetchrow(
        """
        SELECT id, title, category, scheduled_at, status, completed_at, created_at
        FROM schedule_items
        WHERE user_id = $1 AND status = 'pending'
        ORDER BY (scheduled_at IS NULL), scheduled_at, created_at
        LIMIT 1
        """,
        user_id,
    )
    return ScheduleItemOut(**dict(row)) if row else None


def _format_checkin_line(checkin: DailyCheckinOut | None) -> str:
    if not checkin:
        return ""
    parts = []
    if checkin.mood is not None:
        parts.append(f"心情 {checkin.mood}/5")
    if checkin.energy is not None:
        parts.append(f"精力 {checkin.energy}/5")
    if checkin.sleep_hours is not None:
        parts.append(f"睡了 {checkin.sleep_hours} 小时")
    if checkin.small_win:
        parts.append(f"今天想记的小事：{checkin.small_win}")
    return "[今天的状态] " + "，".join(parts) if parts else ""


async def _generate_recommendation(
    user_id: UUID,
    checkin: DailyCheckinOut | None,
    db: asyncpg.Connection,
    redis: aioredis.Redis,
) -> str:
    cache_key = f"today:reco:{user_id}:{date.today().isoformat()}"
    cached = await redis.get(cache_key)
    if cached:
        return cached

    pool = _db._pool
    long_term = await load_long_term(user_id, pool) if pool else ""
    memory_block = await search_memories(user_id, "今天适合做什么小事来照顾自己", db)

    context = "\n".join(filter(None, [_format_checkin_line(checkin), long_term, memory_block]))
    if not context:
        context = "（暂无更多信息）"

    try:
        response = await get_llm().ainvoke([HumanMessage(content=_RECO_PROMPT.format(context=context))])
        text = response.content.strip()
    except Exception:
        text = _FALLBACK_RECOMMENDATION

    await redis.set(cache_key, text, ex=RECOMMENDATION_TTL)
    return text


async def get_today_snapshot(
    user_id: UUID,
    db: asyncpg.Connection,
    redis: aioredis.Redis,
) -> TodaySnapshotOut:
    checkin = await _fetch_checkin(user_id, db)
    next_item = await _fetch_next_schedule_item(user_id, db)
    recommendation = await _generate_recommendation(user_id, checkin, db, redis)
    return TodaySnapshotOut(checkin=checkin, next_schedule_item=next_item, recommendation=recommendation)


async def upsert_checkin(
    user_id: UUID,
    payload: CheckinUpsert,
    db: asyncpg.Connection,
) -> DailyCheckinOut:
    """今天已有记录时，只覆盖本次传入的字段（未传的字段保持原值）。"""
    row = await db.fetchrow(
        """
        INSERT INTO daily_checkins (user_id, checkin_date, mood, energy, sleep_hours, small_win)
        VALUES ($1, CURRENT_DATE, $2, $3, $4, $5)
        ON CONFLICT (user_id, checkin_date) DO UPDATE SET
            mood = COALESCE(EXCLUDED.mood, daily_checkins.mood),
            energy = COALESCE(EXCLUDED.energy, daily_checkins.energy),
            sleep_hours = COALESCE(EXCLUDED.sleep_hours, daily_checkins.sleep_hours),
            small_win = COALESCE(EXCLUDED.small_win, daily_checkins.small_win)
        RETURNING id, checkin_date, mood, energy, sleep_hours, small_win, created_at
        """,
        user_id,
        payload.mood,
        payload.energy,
        payload.sleep_hours,
        payload.small_win,
    )
    return _row_to_checkin(row)
