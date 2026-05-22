from uuid import UUID

import httpx
from fastapi import Header, HTTPException

from app.config import get_settings

_http_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=10)
    return _http_client


async def get_current_user_id(
    authorization: str = Header(None),
) -> UUID:
    """调用 Supabase /auth/v1/user 验证 JWT，返回 user_id。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = authorization.split(" ", 1)[1]
    settings = get_settings()

    resp = await _get_client().get(
        f"{settings.supabase_url}/auth/v1/user",
        headers={
            "Authorization": f"Bearer {token}",
            "apikey": settings.supabase_anon_key,
        },
    )

    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return UUID(resp.json()["id"])
