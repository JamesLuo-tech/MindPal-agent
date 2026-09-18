"""crisis.py 的测试：关键词匹配（第一层）、LLM 语义判断（第二层）、
两层合并的 assess_crisis、热线追加、危机事件审计日志写入。

两层判断的核心行为约定（这是这次改动的重点，之前只有关键词匹配）：
  - 关键词命中 → 直接判定有风险，不用再多花一次 LLM 调用去"确认"
  - 关键词没命中 → 用 LLM 再判一次语义（换一种说法、委婉表达也要能接住）
  - 两层是"或"的关系：LLM 只能把 False 变成 True，不能把关键词已经命中
    的 True 推翻掉
  - LLM 调用本身失败（网络错误等）时，保守地当成"这一层没有额外信号"，
    不能让"调用失败"变成"判定为有风险"——那样一次 API 抖动就会让所有
    消息都触发假警报；但 LLM 输出格式解析不出来时（模型确实返回了内容，
    只是没按格式回答）要保守判断为"有风险"——两种失败模式的正确默认值
    是相反的，测试要把这个区分锁住。
"""
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agent.crisis import (
    HOTLINE_APPEND,
    LLM_DETECTED_LABEL,
    append_hotline_if_triggered,
    assess_crisis,
    build_crisis_classification_prompt,
    classify_crisis_risk,
    find_matched_keyword,
    parse_crisis_classification,
    save_crisis_event,
)


def _llm_returning(content: str):
    llm = MagicMock()
    llm.bind.return_value = llm  # .bind(temperature=0) 返回自身，链式调用照常工作
    response = MagicMock()
    response.content = content
    llm.ainvoke = AsyncMock(return_value=response)
    return llm


# ---------------------------------------------------------------------------
# find_matched_keyword（第一层，行为不变）
# ---------------------------------------------------------------------------


def test_find_matched_keyword_returns_first_match():
    assert find_matched_keyword("我最近特别难受，一点都不想活了") == "不想活"


def test_find_matched_keyword_returns_none_when_no_match():
    assert find_matched_keyword("今天天气不错") is None


# ---------------------------------------------------------------------------
# build_crisis_classification_prompt / parse_crisis_classification
# ---------------------------------------------------------------------------


def test_build_crisis_classification_prompt_includes_text():
    prompt = build_crisis_classification_prompt("我最近感觉撑不下去了")
    assert "我最近感觉撑不下去了" in prompt
    assert "漏判的代价远大于误判" in prompt  # 保守偏向的指令必须在


def test_parse_crisis_classification_recognizes_positive():
    assert parse_crisis_classification("有风险") is True


def test_parse_crisis_classification_recognizes_negative_without_false_positive_on_substring():
    """"有风险"是"没有风险"的子串，不能用简单的 in 判断，必须先排除
    否定表达——这是最容易踩的一个坑，单独锁一条测试。"""
    assert parse_crisis_classification("没有风险") is False
    assert parse_crisis_classification("没风险") is False


def test_parse_crisis_classification_handles_extra_whitespace_and_text():
    assert parse_crisis_classification("  有风险。这句话透露出明显的求助信号。") is True
    assert parse_crisis_classification("判断：没有风险，只是在讨论一部电影。") is False


def test_parse_crisis_classification_defaults_to_true_on_unparseable_output():
    """格式不对/答非所问时保守判断为有风险——跟"LLM 调用失败"的默认值
    刻意相反，见 classify_crisis_risk 那组测试。"""
    assert parse_crisis_classification("这是一句完全不按格式回答的话") is True
    assert parse_crisis_classification("") is True


# ---------------------------------------------------------------------------
# classify_crisis_risk（第二层：LLM 调用 + 失败处理）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_crisis_risk_returns_true_for_positive_classification():
    llm = _llm_returning("有风险")
    assert await classify_crisis_risk("如果哪天我不在了，你们不用找我", llm) is True


@pytest.mark.asyncio
async def test_classify_crisis_risk_returns_false_for_negative_classification():
    llm = _llm_returning("没有风险")
    assert await classify_crisis_risk("今天工作有点累", llm) is False


@pytest.mark.asyncio
async def test_classify_crisis_risk_invokes_with_temperature_zero():
    """安全判断希望结果尽量稳定可复现，不该用主 LLM 默认的高温度采样。"""
    llm = _llm_returning("有风险")
    await classify_crisis_risk("测试消息", llm)
    llm.bind.assert_called_once_with(temperature=0)


@pytest.mark.asyncio
async def test_classify_crisis_risk_defaults_to_false_when_llm_call_fails():
    """LLM 调用本身失败（网络/超时/限流）时保守当成"没有额外信号"，不能让
    一次 API 抖动就把这一轮判定成"有风险"——这跟"LLM 有回复但格式解析不出
    来"的默认值刻意相反。"""
    llm = MagicMock()
    llm.bind.return_value = llm
    llm.ainvoke = AsyncMock(side_effect=RuntimeError("网络错误"))
    assert await classify_crisis_risk("随便一句话", llm) is False


# ---------------------------------------------------------------------------
# assess_crisis（两层合并入口）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assess_crisis_keyword_match_skips_llm_call():
    """关键词已经命中，不该再多花一次 LLM 调用去"确认"。"""
    llm = _llm_returning("没有风险")  # 就算 LLM 会说没风险也不该被问到
    triggered, label = await assess_crisis("我不想活了", llm)
    assert triggered is True
    assert label == "不想活"
    llm.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_assess_crisis_llm_catches_what_keyword_misses():
    """核心场景：关键词完全没命中，但语义上确实有风险——第二层应该能接住。"""
    llm = _llm_returning("有风险")
    triggered, label = await assess_crisis("如果哪天我突然联系不上了，别担心", llm)
    assert triggered is True
    assert label == LLM_DETECTED_LABEL


@pytest.mark.asyncio
async def test_assess_crisis_no_signal_from_either_layer():
    llm = _llm_returning("没有风险")
    triggered, label = await assess_crisis("今天天气不错，出去走了走", llm)
    assert triggered is False
    assert label is None


@pytest.mark.asyncio
async def test_assess_crisis_llm_cannot_override_keyword_hit():
    """两层是"或"的关系——即使 LLM 那层因为某种原因判断"没有风险"，
    也不该被问到（关键词命中直接短路），更不可能推翻关键词的判断。"""
    llm = _llm_returning("没有风险")
    triggered, label = await assess_crisis("我想自杀", llm)
    assert triggered is True
    assert label == "想自杀"
    llm.ainvoke.assert_not_called()


# ---------------------------------------------------------------------------
# append_hotline_if_triggered —— 只负责追加文案，不重新判断
# ---------------------------------------------------------------------------


def test_append_hotline_if_triggered_appends_when_true():
    result = append_hotline_if_triggered("我在", True)
    assert result == "我在" + HOTLINE_APPEND


def test_append_hotline_if_triggered_no_op_when_false():
    result = append_hotline_if_triggered("太好了", False)
    assert result == "太好了"


# ---------------------------------------------------------------------------
# save_crisis_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_crisis_event_passes_correct_params(mock_db):
    user_id = uuid4()
    message_id = uuid4()
    mock_db.execute = AsyncMock()

    await save_crisis_event(user_id, message_id, "不想活", mock_db)

    args = mock_db.execute.call_args.args
    assert "INSERT INTO crisis_events" in args[0]
    assert args[1] == user_id
    assert args[2] == message_id
    assert args[3] == "不想活"


@pytest.mark.asyncio
async def test_save_crisis_event_accepts_llm_detected_label():
    """LLM 单独判断出来的（没有真实关键词），审计日志里存的是占位标识，
    不是 None——不能因为没有关键词原文就漏记这条审计。"""
    mock_db = MagicMock()
    mock_db.execute = AsyncMock()
    await save_crisis_event(uuid4(), uuid4(), LLM_DETECTED_LABEL, mock_db)
    args = mock_db.execute.call_args.args
    assert args[3] == LLM_DETECTED_LABEL


@pytest.mark.asyncio
async def test_save_crisis_event_allows_none_message_id(mock_db):
    """message_id 有可能是 None（比如消息持久化那一步失败了），
    不该因为这个直接崩，crisis_events.message_id 本身也允许为空
    （ON DELETE SET NULL）。"""
    mock_db.execute = AsyncMock()
    await save_crisis_event(uuid4(), None, "跳楼", mock_db)
    args = mock_db.execute.call_args.args
    assert args[2] is None
