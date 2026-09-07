"""load_reflection_note / save_reflection_note 的测试——用 fakeredis 而不是
mock，因为逻辑本身就是"往 Redis 里写一个 key、按情况覆盖/删除"，直接验证
真实的 get/set/delete 行为比 mock 调用参数更可靠。"""
from uuid import uuid4

import fakeredis.aioredis as fakeredis
import pytest
import pytest_asyncio

from app.agent.memory import load_reflection_note, save_reflection_note


@pytest_asyncio.fixture
async def redis():
    client = fakeredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest.mark.asyncio
async def test_load_returns_empty_string_when_nothing_saved(redis):
    user_id = uuid4()
    note = await load_reflection_note(user_id, "convo-1", redis)
    assert note == ""


@pytest.mark.asyncio
async def test_save_then_load_roundtrip(redis):
    user_id = uuid4()
    await save_reflection_note(user_id, "convo-1", "语气有点说教，下次多共情", redis)
    note = await load_reflection_note(user_id, "convo-1", redis)
    assert note == "语气有点说教，下次多共情"


@pytest.mark.asyncio
async def test_save_overwrites_previous_note_not_appends(redis):
    user_id = uuid4()
    await save_reflection_note(user_id, "convo-1", "第一条笔记", redis)
    await save_reflection_note(user_id, "convo-1", "第二条笔记", redis)
    note = await load_reflection_note(user_id, "convo-1", redis)
    assert note == "第二条笔记"  # 不是列表累加，是覆盖


@pytest.mark.asyncio
async def test_save_empty_note_clears_previous_one():
    """这一轮反思没发现问题时应该清空上一条旧笔记，不能让旧问题继续影响后面的对话。"""
    client = fakeredis.FakeRedis(decode_responses=True)
    user_id = uuid4()
    await save_reflection_note(user_id, "convo-1", "上一条问题", client)
    await save_reflection_note(user_id, "convo-1", "", client)
    note = await load_reflection_note(user_id, "convo-1", client)
    assert note == ""
    await client.aclose()


@pytest.mark.asyncio
async def test_different_conversations_have_independent_notes(redis):
    user_id = uuid4()
    await save_reflection_note(user_id, "convo-1", "会话1的笔记", redis)
    await save_reflection_note(user_id, "convo-2", "会话2的笔记", redis)
    assert await load_reflection_note(user_id, "convo-1", redis) == "会话1的笔记"
    assert await load_reflection_note(user_id, "convo-2", redis) == "会话2的笔记"


@pytest.mark.asyncio
async def test_different_users_have_independent_notes(redis):
    user_a, user_b = uuid4(), uuid4()
    await save_reflection_note(user_a, "convo-1", "用户A的笔记", redis)
    assert await load_reflection_note(user_b, "convo-1", redis) == ""
