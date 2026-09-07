"""反思模块的测试：prompt 拼接该不该带上某个检查项、LLM 回复的解析逻辑、
reflect_on_turn 的整体编排——全部 mock 掉 LLM，测的是逻辑，不是真实反思质量
（真实质量靠人工核查 + 后续需要的话可以仿照 eval_router.py 做离线评测）。"""
from unittest.mock import AsyncMock

import pytest

from app.agent.reflection import build_reflection_prompt, parse_reflection_response, reflect_on_turn


# ---------------------------------------------------------------------------
# build_reflection_prompt —— 三个检查项该不该出现
# ---------------------------------------------------------------------------


def test_prompt_always_includes_persona_check():
    prompt = build_reflection_prompt("我今天很难受", "抱抱你", crisis_triggered=False, segment_drafts=None)
    assert "人设" in prompt


def test_prompt_excludes_crisis_check_when_not_triggered():
    prompt = build_reflection_prompt("随便聊聊", "在的", crisis_triggered=False, segment_drafts=None)
    assert "危机语气" not in prompt


def test_prompt_includes_crisis_check_when_triggered():
    prompt = build_reflection_prompt("我不想活了", "我在", crisis_triggered=True, segment_drafts=None)
    assert "危机语气" in prompt


def test_prompt_excludes_multi_intent_check_when_no_drafts():
    prompt = build_reflection_prompt("失眠怎么办", "试试呼吸法", crisis_triggered=False, segment_drafts=None)
    assert "多意图完整性" not in prompt


def test_prompt_includes_multi_intent_check_and_drafts_when_given():
    drafts = [
        {"agent_type": "empathy", "text": "听起来不容易"},
        {"agent_type": "action", "text": "帮你记了一笔心情"},
    ]
    prompt = build_reflection_prompt("我难受，帮我记一下心情", "听起来不容易，已经帮你记了", False, drafts)
    assert "多意图完整性" in prompt
    assert "听起来不容易" in prompt
    assert "帮你记了一笔心情" in prompt


def test_prompt_includes_both_crisis_and_multi_intent_when_both_apply():
    drafts = [{"agent_type": "empathy", "text": "a"}, {"agent_type": "action", "text": "b"}]
    prompt = build_reflection_prompt("msg", "resp", crisis_triggered=True, segment_drafts=drafts)
    assert "危机语气" in prompt
    assert "多意图完整性" in prompt


# ---------------------------------------------------------------------------
# parse_reflection_response
# ---------------------------------------------------------------------------


def test_parse_ok_returns_none():
    assert parse_reflection_response("OK") is None
    assert parse_reflection_response("ok") is None
    assert parse_reflection_response("OK，回复得挺好的") is None  # 只要以 OK 开头就当没问题


def test_parse_problem_extracts_note_with_english_colon():
    result = parse_reflection_response("问题: 语气有点说教，下次多共情少建议")
    assert result == "语气有点说教，下次多共情少建议"


def test_parse_problem_extracts_note_with_chinese_colon():
    result = parse_reflection_response("问题：漏掉了知识意图那部分")
    assert result == "漏掉了知识意图那部分"


def test_parse_garbage_defaults_to_none():
    """解析不出格式的内容一律当没问题处理，宁可漏掉也不要把无关内容存进 Redis。"""
    assert parse_reflection_response("这条回复整体还不错，语气也挺自然的") is None


def test_parse_empty_defaults_to_none():
    assert parse_reflection_response("") is None


def test_parse_problem_with_empty_note_returns_none():
    assert parse_reflection_response("问题:") is None


# ---------------------------------------------------------------------------
# reflect_on_turn —— 整体编排
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reflect_on_turn_returns_none_when_llm_says_ok():
    mock_response = AsyncMock()
    mock_response.content = "OK"
    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    result = await reflect_on_turn("你好", "在的呀", False, None, mock_llm)

    assert result is None
    mock_llm.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_reflect_on_turn_returns_note_when_llm_flags_issue():
    mock_response = AsyncMock()
    mock_response.content = "问题: 危机场景下语气太生硬，下次先接住情绪再说别的"
    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    result = await reflect_on_turn("我不想活了", "记得看安全计划", True, None, mock_llm)

    assert result == "危机场景下语气太生硬，下次先接住情绪再说别的"
