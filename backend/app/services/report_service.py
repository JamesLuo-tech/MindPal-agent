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

    summary = await _generate_summary(emotion_trend, key_events)

    return {
        "period": f"{since.strftime('%Y-%m-%d')} ~ {now.strftime('%Y-%m-%d')}",
        "emotion_trend": emotion_trend,
        "key_events": key_events,
        "summary": summary,
    }


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
