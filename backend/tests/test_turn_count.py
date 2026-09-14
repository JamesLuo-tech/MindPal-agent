"""increment_turn_count 的测试——用 fakeredis 验证真实的 INCR/EXPIRE 行为。

这条计数器是为了修一个真实 bug：之前用 len(short_term)//2+1 算轮数，
但短期记忆最多保留 10 轮，超过之后 len(short_term) 永远卡在上限，
"每 5 轮存一次向量记忆"这个判断从此再也不会触发——下面几条用例专门
验证新的计数器不会重现这个问题（持续递增、不会卡在某个值上）。
"""
from uuid import uuid4

import fakeredis.aioredis as fakeredis
import pytest
import pytest_asyncio

from app.agent.memory import SHORT_TERM_TTL, increment_turn_count


@pytest_asyncio.fixture
async def redis():
    client = fakeredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest.mark.asyncio
async def test_first_call_returns_one(redis):
    user_id = uuid4()
    count = await increment_turn_count(user_id, "convo-1", redis)
    assert count == 1


@pytest.mark.asyncio
async def test_increments_on_each_call(redis):
    user_id = uuid4()
    counts = [await increment_turn_count(user_id, "convo-1", redis) for _ in range(3)]
    assert counts == [1, 2, 3]


@pytest.mark.asyncio
async def test_keeps_incrementing_past_short_term_memory_cap():
    """这是修复的核心场景：short_term 最多存 10 轮就会卡住，但这个计数器
    应该完全不受影响，一直数到 20、30 轮都不会停在某个值上不动。"""
    client = fakeredis.FakeRedis(decode_responses=True)
    user_id = uuid4()
    for _ in range(19):
        await increment_turn_count(user_id, "long-convo", client)
    count_20 = await increment_turn_count(user_id, "long-convo", client)
    assert count_20 == 20  # 不是卡在 11
    assert count_20 % 5 == 0  # "每 5 轮存一次"的判断在第 20 轮能正常触发
    await client.aclose()


@pytest.mark.asyncio
async def test_different_conversations_have_independent_counters(redis):
    user_id = uuid4()
    await increment_turn_count(user_id, "convo-1", redis)
    await increment_turn_count(user_id, "convo-1", redis)
    count_convo_2 = await increment_turn_count(user_id, "convo-2", redis)
    assert count_convo_2 == 1  # 不同会话的计数互不影响


@pytest.mark.asyncio
async def test_different_users_have_independent_counters(redis):
    user_a, user_b = uuid4(), uuid4()
    await increment_turn_count(user_a, "convo-1", redis)
    count_b = await increment_turn_count(user_b, "convo-1", redis)
    assert count_b == 1


@pytest.mark.asyncio
async def test_sets_ttl_on_the_counter_key(redis):
    user_id = uuid4()
    await increment_turn_count(user_id, "convo-1", redis)
    ttl = await redis.ttl(f"turncount:{user_id}:convo-1")
    assert 0 < ttl <= SHORT_TERM_TTL
