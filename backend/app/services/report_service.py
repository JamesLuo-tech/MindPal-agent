"""周报生成服务。"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

import asyncpg
from langchain_core.messages import HumanMessage

from app.agent.llm import get_llm

_SUMMARY_PROMPT = """\
以下是用户近 7 天的情绪数据，请用温和朋友的口吻写一段短小的回顾（不超过 150 字）。
不要分析，不要给建议，就像老朋友陪着回顾这一周那样，自然地说出来。
只输出正文，不要加标题。

情绪数据：
{trend_text}"""


async def generate_weekly_report(user_id: UUID, db: asyncpg.Connection) -> dict:
    """基于近 7 天 emotions 和 key_events 数据，生成叙述性周报。"""
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=7)

    emotion_rows = await db.fetch(
        """
        SELECT primary_emotion, intensity, created_at
        FROM emotions
        WHERE user_id = $1 AND created_at >= $2
        ORDER BY created_at
        """,
        user_id,
        since,
    )

    # 按天聚合
    daily: dict[str, list[dict]] = defaultdict(list)
    for row in emotion_rows:
        day = row["created_at"].strftime("%Y-%m-%d")
        daily[day].append({
            "emotion": row["primary_emotion"] or "其他",
            "intensity": row["intensity"] or 5,
        })

    emotion_trend = []
    for day in sorted(daily.keys()):
        items = daily[day]
        avg = round(sum(i["intensity"] for i in items) / len(items), 1)
        dominant = Counter(i["emotion"] for i in items).most_common(1)[0][0]
        emotion_trend.append({
            "date": day,
            "avg_intensity": avg,
            "dominant_emotion": dominant,
            "count": len(items),
        })

    event_rows = await db.fetch(
        """
        SELECT event_type, content, created_at
        FROM key_events
        WHERE user_id = $1 AND created_at >= $2
        ORDER BY created_at DESC
        LIMIT 10
        """,
        user_id,
        since,
    )
    key_events = [
        {
            "type": r["event_type"],
            "content": r["content"],
            "date": r["created_at"].strftime("%Y-%m-%d"),
        }
        for r in event_rows
    ]

    activity_trend = await _build_activity_trend(user_id, now, since, db)

    summary = await _generate_summary(emotion_trend, key_events)

    return {
        "period": f"{since.strftime('%Y-%m-%d')} ~ {now.strftime('%Y-%m-%d')}",
        "emotion_trend": emotion_trend,
        "key_events": key_events,
        "summary": summary,
        "activity_trend": activity_trend,
    }


async def _build_activity_trend(
    user_id: UUID, now: datetime, since: datetime, db: asyncpg.Connection,
) -> list[dict]:
    """近 7 天（含今天）每日心情/精力/睡眠（今日速记）+ 完成的小步行动数量。

    跟 emotion_trend 不同，这里覆盖全部 7 个日历日（没记录的天数字段为 None），
    好让前端折线图连续，不会因为某天没打卡就断线。
    """
    checkin_rows = await db.fetch(
        """
        SELECT checkin_date, mood, energy, sleep_hours
        FROM daily_checkins
        WHERE user_id = $1 AND checkin_date >= $2
        """,
        user_id,
        since.date(),
    )
    completed_rows = await db.fetch(
        """
        SELECT completed_at
        FROM schedule_items
        WHERE user_id = $1 AND status = 'done' AND completed_at >= $2
        """,
        user_id,
        since,
    )

    checkin_by_day = {r["checkin_date"].strftime("%Y-%m-%d"): r for r in checkin_rows}
    completed_by_day: dict[str, int] = defaultdict(int)
    for r in completed_rows:
        if r["completed_at"]:
            completed_by_day[r["completed_at"].strftime("%Y-%m-%d")] += 1

    # 按日历日回溯 7 天，today 本身是最后一个点——避免只用 since+i 导致漏掉今天
    trend = []
    for i in range(6, -1, -1):
        day = (now.date() - timedelta(days=i)).strftime("%Y-%m-%d")
        checkin = checkin_by_day.get(day)
        trend.append({
            "date": day,
            "avg_mood": checkin["mood"] if checkin else None,
            "avg_energy": checkin["energy"] if checkin else None,
            "avg_sleep_hours": float(checkin["sleep_hours"]) if checkin and checkin["sleep_hours"] is not None else None,
            "completed_steps": completed_by_day.get(day, 0),
        })
    return trend


async def _generate_summary(
    emotion_trend: list[dict],
    key_events: list[dict],
) -> str:
    if not emotion_trend:
        return "这周还没有情绪记录，随时都可以来聊。"

    lines = []
    for item in emotion_trend:
        lines.append(
            f"{item['date']}：{item['dominant_emotion']}为主，平均强度 {item['avg_intensity']}/10"
        )
    if key_events:
        lines.append("关键事件：")
        for ev in key_events[:5]:
            lines.append(f"  {ev['date']} [{ev['type']}] {ev['content'][:60]}")

    prompt = _SUMMARY_PROMPT.format(trend_text="\n".join(lines))

    try:
        response = await get_llm().ainvoke([HumanMessage(content=prompt)])
        return response.content.strip()
    except Exception:
        return "这周有过一些情绪起伏，谢谢你一直在说。"
