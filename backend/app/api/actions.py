"""Agent 写入类工具的"确认后执行"入口。

POST /api/chat/actions/confirm - 用户在确认卡片上点了"确认"之后才会调用。
只接收 proposal_id——action/params 从服务端存的提议记录里取，不信任客户端
重新传回来的值；会校验所有权、状态（pending 才能确认）、TTL，真正的数据库
写入只发生在这里，而且在一个事务里完成"执行 + 标记已确认"。
"""
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user_id
from app.database import get_db
from app.schemas.actions import ActionConfirmRequest
from app.services.action_proposal_service import (
    ProposalAlreadyProcessedError,
    ProposalExpiredError,
    ProposalNotFoundError,
    confirm_proposal,
)

router = APIRouter()


@router.post("/chat/actions/confirm")
async def confirm_action(
    body: ActionConfirmRequest,
    user_id: UUID = Depends(get_current_user_id),
    db: asyncpg.Connection = Depends(get_db),
):
    try:
        return await confirm_proposal(user_id, body.proposal_id, db)
    except ProposalNotFoundError:
        raise HTTPException(status_code=404, detail="提议不存在或已失效")
    except ProposalExpiredError:
        raise HTTPException(status_code=410, detail="这条提议已经过期，请重新在对话里操作一次")
    except ProposalAlreadyProcessedError as e:
        raise HTTPException(status_code=409, detail=f"这条提议已经是 {e.status} 状态，无法再次确认")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"参数不合法或执行失败: {e}")
