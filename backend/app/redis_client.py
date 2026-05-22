import redis.asyncio as aioredis
from app.config import get_settings

_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        settings = get_settings()
        try:
            client = aioredis.from_url(settings.redis_url, decode_responses=True)
            await client.ping()
            _redis = client
        except Exception:
            # 连不上真实 Redis 时使用内存模式（开发/演示用）
            import fakeredis.aioredis as fakeredis
            _redis = fakeredis.FakeRedis(decode_responses=True)
            print("[DEV] Redis 不可用，已切换为内存模式（fakeredis）")
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None
