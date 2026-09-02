import json

import asyncpg
from typing import AsyncGenerator
from pgvector.asyncpg import register_vector
from app.config import get_settings

_pool: asyncpg.Pool | None = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    """每个连接建立时注册类型编解码，使 asyncpg 能正确处理特殊列类型。"""
    await register_vector(conn)

    # asyncpg 默认不会把 jsonb/json 列解码成 Python 对象，读出来是原始 JSON 文本，
    # 写代码那边就都不用再手动 json.dumps() 了——直接传 list/dict，靠 ::jsonb 转型触发编码。
    for pg_type in ("jsonb", "json"):
        await conn.set_type_codec(
            pg_type,
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )


async def init_pool() -> None:
    global _pool
    settings = get_settings()
    _pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=2,
        max_size=10,
        command_timeout=60,
        statement_cache_size=0,  # Supabase Pooler 兼容
        init=_init_connection,
    )


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def get_db() -> AsyncGenerator[asyncpg.Connection, None]:
    if _pool is None:
        raise RuntimeError("Database pool not initialized")
    async with _pool.acquire() as conn:
        yield conn
