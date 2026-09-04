"""问诊摘要（Appointment Summary）：把用户一段时间的自我记录整理成
可以直接带给医生/咨询师看的要点列表。

刻意不用 LLM 生成这些要点——这是要给专业人士参考的内容，数字必须真实可信，
所以每一条都是从真实数据算出来的确定性统计，样本量不够就不说，不瞎编。
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

import asyncpg

from app.schemas.summary import AppointmentSummaryOut

# "困难"情绪集合，用来判断某个时段/某次记录是不是偏负面——跟前端 EMOTION_COLOR
# 里区分出的低落类情绪保持一致（悲伤/焦虑/愤怒/恐惧/无助/孤独/疲惫/麻木）
_DIFFICULT_EMOTIONS = {"悲伤", "焦虑", "愤怒", "恐惧", "无助", "孤独", "疲惫", "麻木"}
_CALM_EMOTIONS = {"平静", "希望"}

# 判定"有明显规律"需要的最小样本量——数据太少时宁可不说，也不瞎猜
_MIN_SAMPLES_FOR_PATTERN = 3
_ACTIVITY_FOLLOWUP_WINDOW = timedelta(hours=3)


def _time_bucket(hour: int) -> str:
    if 5 <= hour < 11:
        return "早上"
    if 11 <= hour < 14:
        return "中午"
    if 14 <= hour < 18:
        return "下午"
    if 18 <= hour < 23:
        return "晚上"
    return "深夜"


def _emotion_time_bucket_bullet(emotion_rows: list) -> str | None:
    """哪个时段的"困难"情绪记录占比最高，样本不够或没有明显偏向就不说。"""
    if not emotion_rows:
        return None

    bucket_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [difficult, total]
    for r in emotion_rows:
        bucket = _time_bucket(r["created_at"].hour)
        bucket_counts[bucket][1] += 1
        if r["primary_emotion"] in _DIFFICULT_EMOTIONS:
            bucket_counts[bucket][0] += 1

    candidates = [
        (bucket, difficult, total)
        for bucket, (difficult, total) in bucket_counts.items()
        if total >= 2 and difficult / total > 0.5  # 要求过半，正好五五开不算"明显偏向"
    ]
    if not candidates:
        return None

    bucket, difficult, total = max(candidates, key=lambda c: c[1] / c[2])
    return f"情绪低落/困难的记录主要出现在{bucket}（{difficult}/{total} 次）"


def _sleep_bullet(checkin_rows: list, days: int) -> str | None:
    """平均睡眠时长，样本足够时顺带看看前后半段有没有明显趋势。"""
    values = [
        (r["checkin_date"], float(r["sleep_hours"]))
        for r in checkin_rows
        if r["sleep_hours"] is not None
    ]
    if len(values) < _MIN_SAMPLES_FOR_PATTERN:
        return None

    avg = sum(v for _, v in values) / len(values)
    trend = ""
    if len(values) >= 4:
        values.sort(key=lambda v: v[0])
        half = len(values) // 2
        first_avg = sum(v for _, v in values[:half]) / half
        second_avg = sum(v for _, v in values[half:]) / (len(values) - half)
        if second_avg - first_avg <= -1:
            trend = "，且后半段明显比前半段短"
        elif second_avg - first_avg >= 1:
            trend = "，且后半段明显比前半段长"

    return f"过去{days}天平均睡眠 {avg:.1f} 小时{trend}"


def _completion_rate_bullet(action_rows: list) -> str | None:
    total = len(action_rows)
    if total < _MIN_SAMPLES_FOR_PATTERN:
        return None
    done = sum(1 for r in action_rows if r["status"] == "done")
    rate = round(done / total * 100)
    return f"记录的 {total} 个小行动里完成了 {done} 个（{rate}%）"


def _top_triggers_bullet(emotion_rows: list) -> str | None:
    counter: Counter[str] = Counter()
    for r in emotion_rows:
        for t in r["triggers"] or []:
            counter[t] += 1
    top = counter.most_common(3)
    if not top:
        return None
    return "最近提到最多的触发因素：" + "、".join(f"{t}（{c} 次）" for t, c in top)


def _activity_followup_bullet(action_rows: list, emotion_rows: list) -> str | None:
    """完成小行动之后的一段时间内，情绪记录是不是偏平静——简化版关联分析，
    不是严谨的因果推断，只是给一个"看起来有没有关系"的粗略信号。"""
    calm_after = 0
    difficult_after = 0
    for a in action_rows:
        if a["status"] != "done" or not a["completed_at"]:
            continue
        window_end = a["completed_at"] + _ACTIVITY_FOLLOWUP_WINDOW
        for r in emotion_rows:
            if a["completed_at"] < r["created_at"] <= window_end:
                if r["primary_emotion"] in _CALM_EMOTIONS:
                    calm_after += 1
                elif r["primary_emotion"] in _DIFFICULT_EMOTIONS:
                    difficult_after += 1

    total = calm_after + difficult_after
    if total < _MIN_SAMPLES_FOR_PATTERN or calm_after <= difficult_after:
        return None
    return "完成小行动之后的几小时内，情绪记录通常偏向平静"


async def generate_appointment_summary(
    user_id: UUID,
    days: int,
    discuss_topics: str | None,
    db: asyncpg.Connection,
) -> AppointmentSummaryOut:
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    emotion_rows = await db.fetch(
        """
        SELECT primary_emotion, triggers, created_at
        FROM emotions WHERE user_id = $1 AND created_at >= $2
        ORDER BY created_at
        """,
        user_id, since,
    )
    checkin_rows = await db.fetch(
        """
        SELECT checkin_date, sleep_hours
        FROM daily_checkins WHERE user_id = $1 AND checkin_date >= $2
        """,
        user_id, since.date(),
    )
    action_rows = await db.fetch(
        """
        SELECT status, completed_at
        FROM schedule_items WHERE user_id = $1 AND created_at >= $2
        """,
        user_id, since,
    )

    bullets = [
        b for b in (
            _emotion_time_bucket_bullet(emotion_rows),
            _sleep_bullet(checkin_rows, days),
            _completion_rate_bullet(action_rows),
            _top_triggers_bullet(emotion_rows),
            _activity_followup_bullet(action_rows, emotion_rows),
        )
        if b
    ]

    if not bullets:
        bullets = [f"过去{days}天的记录还不够多，暂时看不出明显规律——多记录几天会更准确"]

    return AppointmentSummaryOut(
        period=f"{since.date()} ~ {now.date()}",
        bullets=bullets,
        discuss_topics=discuss_topics,
        generated_at=now,
    )
