from uuid import UUID
from fastapi import Depends
import asyncpg
import redis.asyncio as aioredis

from app.core.auth import get_current_user_id
from app.database import get_db
from app.redis_client import get_redis

# 常用依赖别名，路由里直接 Depends(CurrentUser) / Depends(DB) / Depends(Redis)
CurrentUser = Depends(get_current_user_id)
DB = Depends(get_db)
Redis = Depends(get_redis)
