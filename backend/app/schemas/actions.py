from uuid import UUID

from pydantic import BaseModel


class ActionConfirmRequest(BaseModel):
    """确认接口现在只接收 proposal_id——action/params 从服务端存的提议记录里
    取，不再信任客户端重新传回来的这两项，堵住"直接拿任意 action+params
    调确认接口、跳过真实提议"这条路。"""
    proposal_id: UUID
