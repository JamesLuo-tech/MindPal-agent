"""问诊摘要统计逻辑的测试——重点验证"样本不够就不该瞎说"、方向判断对不对，
以及最终这些数字是真实计算出来的，不是模型编的。"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.services.appointment_summary_service import (
    _activity_followup_bullet,
    _completion_rate_bullet,
    _emotion_time_bucket_bullet,
    _sleep_bullet,
    _time_bucket,
    _top_triggers_bullet,
    generate_appointment_summary,
)

NOW = datetime(2026, 9, 2, 20, 0, tzinfo=timezone.utc)


def _emotion(hour: int, emotion: str, triggers=None, day_offset: int = 0):
    return {
        "primary_emotion": emotion,
        "triggers": triggers or [],
        "created_at": (NOW - timedelta(days=day_offset)).replace(hour=hour, minute=0, second=0, microsecond=0),
    }


def _checkin(day_offset: int, sleep_hours: float):
    return {"checkin_date": (NOW - timedelta(days=day_offset)).date(), "sleep_hours": sleep_hours}


def _action(status: str, completed_at=None):
    return {"status": status, "completed_at": completed_at}


class TestTimeBucket:
    def test_boundaries(self):
        assert _time_bucket(5) == "早上"
        assert _time_bucket(10) == "早上"
        assert _time_bucket(11) == "中午"
        assert _time_bucket(13) == "中午"
        assert _time_bucket(14) == "下午"
        assert _time_bucket(17) == "下午"
        assert _time_bucket(18) == "晚上"
        assert _time_bucket(22) == "晚上"
        assert _time_bucket(23) == "深夜"
        assert _time_bucket(3) == "深夜"


class TestEmotionTimeBucketBullet:
    def test_no_data_returns_none(self):
        assert _emotion_time_bucket_bullet([]) is None

    def test_too_few_samples_in_every_bucket_returns_none(self):
        rows = [_emotion(20, "悲伤", day_offset=0)]  # 只有 1 条，不够判断
        assert _emotion_time_bucket_bullet(rows) is None

    def test_clear_evening_pattern_is_detected(self):
        rows = [
            _emotion(20, "悲伤", day_offset=0),
            _emotion(21, "焦虑", day_offset=1),
            _emotion(9, "希望", day_offset=2),  # 早上是平静的，不该被算进"困难"
        ]
        result = _emotion_time_bucket_bullet(rows)
        assert result is not None
        assert "晚上" in result
        assert "2/2" in result

    def test_no_clear_skew_returns_none(self):
        """困难情绪均匀分布在各个时段，没有哪个时段占比过半，不该瞎猜。"""
        rows = [
            _emotion(9, "悲伤", day_offset=0),
            _emotion(9, "希望", day_offset=1),
            _emotion(20, "焦虑", day_offset=0),
            _emotion(20, "平静", day_offset=1),
        ]
        assert _emotion_time_bucket_bullet(rows) is None


class TestSleepBullet:
    def test_fewer_than_3_samples_returns_none(self):
        rows = [_checkin(0, 6.0), _checkin(1, 7.0)]
        assert _sleep_bullet(rows, days=14) is None

    def test_reports_average_without_trend_when_stable(self):
        rows = [_checkin(i, 7.0) for i in range(4)]
        result = _sleep_bullet(rows, days=14)
        assert result is not None
        assert "7.0" in result
        assert "趋势" not in result

    def test_detects_declining_trend(self):
        # 前半段（更早）睡得多，后半段（更近）睡得少
        rows = [
            _checkin(6, 9.0), _checkin(5, 9.0),
            _checkin(1, 5.0), _checkin(0, 5.0),
        ]
        result = _sleep_bullet(rows, days=14)
        assert "明显比前半段短" in result

    def test_ignores_missing_sleep_hours(self):
        rows = [_checkin(0, 7.0), _checkin(1, 7.0), {"checkin_date": NOW.date(), "sleep_hours": None}]
        # 只有 2 条有效数据，不够 3 条阈值
        assert _sleep_bullet(rows, days=14) is None


class TestCompletionRateBullet:
    def test_fewer_than_3_items_returns_none(self):
        assert _completion_rate_bullet([_action("done"), _action("pending")]) is None

    def test_computes_correct_percentage(self):
        rows = [_action("done"), _action("done"), _action("pending"), _action("skipped")]
        result = _completion_rate_bullet(rows)
        assert "4 个小行动" in result
        assert "完成了 2 个" in result
        assert "50%" in result


class TestTopTriggersBullet:
    def test_no_triggers_returns_none(self):
        assert _top_triggers_bullet([_emotion(10, "悲伤", triggers=[])]) is None

    def test_ranks_by_frequency(self):
        rows = [
            _emotion(10, "焦虑", triggers=["工作压力"]),
            _emotion(11, "焦虑", triggers=["工作压力", "睡眠不足"]),
            _emotion(12, "悲伤", triggers=["和朋友吵架"]),
        ]
        result = _top_triggers_bullet(rows)
        assert "工作压力（2 次）" in result
        assert result.index("工作压力") < result.index("睡眠不足")  # 出现频率高的排前面


class TestActivityFollowupBullet:
    def test_too_few_followups_returns_none(self):
        completed = NOW - timedelta(hours=1)
        actions = [_action("done", completed_at=completed)]
        emotions = [{"primary_emotion": "平静", "triggers": [], "created_at": completed + timedelta(minutes=30)}]
        assert _activity_followup_bullet(actions, emotions) is None

    def test_detects_calm_after_pattern(self):
        actions = []
        emotions = []
        for i in range(3):
            completed = NOW - timedelta(days=i, hours=-1)
            actions.append(_action("done", completed_at=completed))
            emotions.append({
                "primary_emotion": "平静", "triggers": [],
                "created_at": completed + timedelta(hours=1),
            })
        result = _activity_followup_bullet(actions, emotions)
        assert result is not None
        assert "平静" in result

    def test_pending_actions_are_ignored(self):
        actions = [_action("pending")]
        emotions = [{"primary_emotion": "平静", "triggers": [], "created_at": NOW}]
        assert _activity_followup_bullet(actions, emotions) is None

    def test_emotions_outside_the_followup_window_are_not_counted(self):
        completed = NOW - timedelta(days=1)
        actions = [_action("done", completed_at=completed)] * 3
        # 情绪记录在完成 6 小时之后，超出 3 小时的跟进窗口
        emotions = [{"primary_emotion": "平静", "triggers": [], "created_at": completed + timedelta(hours=6)}] * 3
        assert _activity_followup_bullet(actions, emotions) is None


@pytest.mark.asyncio
async def test_generate_appointment_summary_falls_back_when_no_data(mock_db):
    mock_db.fetch = AsyncMock(return_value=[])
    from uuid import uuid4

    result = await generate_appointment_summary(uuid4(), 14, None, mock_db)

    assert len(result.bullets) == 1
    assert "还不够多" in result.bullets[0]
    assert result.discuss_topics is None


@pytest.mark.asyncio
async def test_generate_appointment_summary_passes_through_discuss_topics(mock_db):
    mock_db.fetch = AsyncMock(return_value=[])
    from uuid import uuid4

    result = await generate_appointment_summary(uuid4(), 14, "注意力下降和持续疲惫", mock_db)

    assert result.discuss_topics == "注意力下降和持续疲惫"


@pytest.mark.asyncio
async def test_generate_appointment_summary_rejects_invalid_days_at_schema_level():
    from app.schemas.summary import AppointmentSummaryRequest
    with pytest.raises(Exception):
        AppointmentSummaryRequest(days=0)
    with pytest.raises(Exception):
        AppointmentSummaryRequest(days=91)
