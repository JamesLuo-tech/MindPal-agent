"""Agent 写入类工具的"确认后执行"入口。

POST /api/chat/actions/confirm - 用户在确认卡片上点了"确认"之后才会调用；
不经过 LLM，按用户确认的参数重新校验后直接调用 service 层，真正的数据库写入只发生在这里。
"""
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.agent.actions import ACTION_DISPATCH
from app.core.auth import get_current_user_id
from app.database import get_db

router = APIRouter()


class ActionConfirmRequest(BaseModel):
    action: str
    params: dict


@router.post("/chat/actions/confirm")
async def confirm_action(
    body: ActionConfirmRequest,
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
):
    handler = ACTION_DISPATCH.get(body.action)
    if not handler:
        raise HTTPException(status_code=400, detail=f"未知的 action: {body.action}")
    try:
        result = await handler(user_id, body.params, db)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"参数不合法或执行失败: {e}")
    return {"action": body.action, "result": result}
