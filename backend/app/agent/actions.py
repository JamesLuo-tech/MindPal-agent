"""Agent 的"写入类"工具——只生成结构化提议，不碰数据库。

真正的数据库写入要等用户在前端确认卡片上点确认之后，
由 /api/chat/actions/confirm 走 ACTION_DISPATCH 里同一套 service 层函数执行，
LLM 全程摸不到 SQL，也没有任何工具能未经确认直接落库。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

import asyncpg
from langchain_core.tools import tool

import app.database as _db
from app.agent.memory import save_memory as _save_memory_to_vector
from app.schemas.coping import CopingResultCreate
from app.schemas.goals import ScheduleItemCreate, ScheduleItemUpdate
from app.schemas.support import SafetyPlanUpsert
from app.schemas.today import CheckinUpsert
from app.services import coping_service, goals_service, support_service, today_service


def _proposal(action: str, params: dict, summary: str) -> str:
    return json.dumps({"action": action, "params": params, "summary": summary}, ensure_ascii=False)


# =====================================================================
# 提议工具：LLM 能调用的，只生成待确认的结构化提议
# =====================================================================


@tool
def propose_record_mood(
    mood: int | None = None,
    energy: int | None = None,
    sleep_hours: float | None = None,
    small_win: str | None = None,
) -> str:
    """用户在聊天里主动提到了自己的心情/精力/睡眠情况时，用这个工具整理成一条待确认的记录。
    只在用户明确提到具体感受时用，不要凭空猜。1-5 分制，没提到的字段留空。

    Args:
        mood: 心情 1-5
        energy: 精力 1-5
        sleep_hours: 睡了几小时
        small_win: 简短备注，比如用户提到的具体状况
    """
    params = {"mood": mood, "energy": energy, "sleep_hours": sleep_hours, "small_win": small_win}
    bits = []
    if mood is not None:
        bits.append(f"心情 {mood}/5")
    if energy is not None:
        bits.append(f"精力 {energy}/5")
    if sleep_hours is not None:
        bits.append(f"睡眠 {sleep_hours} 小时")
    if small_win:
        bits.append(f"备注：{small_win}")
    summary = ("记一笔今天的状态：" + "，".join(bits)) if bits else "记一笔今天的状态"
    return _proposal("record_mood", params, summary)


@tool
def propose_create_micro_action(title: str, category: str | None = None) -> str:
    """用户提到想做、或你建议 ta 做一件具体的小事时（散步、喝水、洗澡这类低门槛动作），
    用这个工具把它整理成一条待确认的行动计划。

    Args:
        title: 这件小事的具体描述，比如"出门散步 10 分钟"
        category: 分类标签，如 walk/shower/eat/contact_friend/breathe/journal，不确定就留空
    """
    params = {"title": title, "category": category, "scheduled_at": None}
    return _proposal("create_micro_action", params, f"加一条小行动：{title}")


@tool
def propose_update_action_status(title_hint: str, status: str) -> str:
    """用户提到完成、放弃或跳过了之前提到过的某个小行动时，用这个工具标记状态。
    status 只能是 'done' 或 'skipped'。

    Args:
        title_hint: 用户提到的这件事的关键词（不用完全一致，会模糊匹配最近一条待办）
        status: 'done' 完成了，'skipped' 跳过/放弃了
    """
    status = status if status in ("done", "skipped") else "done"
    verb = "完成" if status == "done" else "跳过"
    params = {"title_hint": title_hint, "status": status}
    return _proposal("update_action_status", params, f"把「{title_hint}」标记为{verb}")


@tool
def propose_schedule_checkin(note: str, minutes_from_now: int | None = None) -> str:
    """约定稍后（比如 10 分钟后，或晚上）再回来问一下用户情况如何时用这个工具。

    Args:
        note: 到时候要问的内容，比如"问问刚才那件事有没有好一点"
        minutes_from_now: 多少分钟后跟进，不确定就留空（默认当晚跟进）
    """
    minutes = minutes_from_now if minutes_from_now and minutes_from_now > 0 else 240
    scheduled_at = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
    params = {"title": note, "category": "checkin", "scheduled_at": scheduled_at}
    when = f"{minutes_from_now} 分钟后" if minutes_from_now else "晚些时候"
    return _proposal("schedule_checkin", params, f"{when}回来问问：{note}")


@tool
def propose_record_coping_result(method: str, helped: bool | None = None, note: str | None = None) -> str:
    """用户提到尝试了某个应对方法、并且说了有没有用时，用这个工具记下来。

    Args:
        method: 用了什么方法，比如"听音乐""深呼吸"
        helped: 有没有用，不确定就留空
        note: 补充说明
    """
    params = {"method": method, "helped": helped, "note": note}
    verdict = "有用" if helped is True else "没什么用" if helped is False else "试过了"
    return _proposal("record_coping_result", params, f"记一下：{method} {verdict}")


@tool
def propose_save_memory(summary: str) -> str:
    """当你判断某个偏好、触发因素、或者被反复验证有效的方法值得长期记住时，
    用这个工具生成一条待确认的长期记忆——不要每次小事都调用，只在真正值得记住时用。

    Args:
        summary: 要记住的内容，简洁的一两句话
    """
    params = {"summary": summary}
    return _proposal("save_memory", params, f"记进长期记忆：{summary}")


@tool
def propose_update_safety_plan(
    warning_signs: str | None = None,
    internal_coping: str | None = None,
    distraction_people_places: str | None = None,
    help_contacts: str | None = None,
    professional_contacts: str | None = None,
    safe_environment: str | None = None,
) -> str:
    """只有当用户明确讨论并同意要更新安全计划的某一部分时才用这个工具，只填用户明确提到的字段。
    这是敏感信息，不确定就不要调用。

    Args:
        warning_signs: 预警信号
        internal_coping: 内在应对策略
        distraction_people_places: 让自己分心的人/地方
        help_contacts: 可以求助的人
        professional_contacts: 专业求助渠道
        safe_environment: 让环境更安全
    """
    params = {
        "warning_signs": warning_signs,
        "internal_coping": internal_coping,
        "distraction_people_places": distraction_people_places,
        "help_contacts": help_contacts,
        "professional_contacts": professional_contacts,
        "safe_environment": safe_environment,
    }
    filled = [f"{k}：{v}" for k, v in params.items() if v]
    summary = ("更新安全计划——" + "；".join(filled)) if filled else "更新安全计划"
    return _proposal("update_safety_plan", params, summary)


ACTION_TOOLS = [
    propose_record_mood,
    propose_create_micro_action,
    propose_update_action_status,
    propose_schedule_checkin,
    propose_record_coping_result,
    propose_save_memory,
    propose_update_safety_plan,
]
ACTION_TOOL_NAMES = {t.name for t in ACTION_TOOLS}


# =====================================================================
# 确认后真正执行：每个 action 名对应一个执行函数，重新校验参数再调用 service
# =====================================================================


async def _exec_record_mood(user_id: UUID, params: dict, db: asyncpg.Connection) -> dict:
    payload = CheckinUpsert(**params)
    result = await today_service.upsert_checkin(user_id, payload, db)
    return result.model_dump(mode="json")


async def _exec_create_micro_action(user_id: UUID, params: dict, db: asyncpg.Connection) -> dict:
    payload = ScheduleItemCreate(**params)
    result = await goals_service.create_schedule_item(user_id, payload, db)
    return result.model_dump(mode="json")


async def _exec_update_action_status(user_id: UUID, params: dict, db: asyncpg.Connection) -> dict:
    title_hint = params["title_hint"]
    status = params["status"]
    row = await db.fetchrow(
        """
        SELECT id FROM schedule_items
        WHERE user_id = $1 AND status = 'pending' AND title ILIKE '%' || $2 || '%'
        ORDER BY created_at DESC LIMIT 1
        """,
        user_id,
        title_hint,
    )
    if not row:
        return {"error": f"没找到匹配「{title_hint}」的待办事项"}
    result = await goals_service.update_schedule_item(
        user_id, row["id"], ScheduleItemUpdate(status=status), db,
    )
    return result.model_dump(mode="json") if result else {"error": "更新失败"}


async def _exec_schedule_checkin(user_id: UUID, params: dict, db: asyncpg.Connection) -> dict:
    payload = ScheduleItemCreate(**params)
    result = await goals_service.create_schedule_item(user_id, payload, db)
    return result.model_dump(mode="json")


async def _exec_record_coping_result(user_id: UUID, params: dict, db: asyncpg.Connection) -> dict:
    payload = CopingResultCreate(**params)
    result = await coping_service.create_coping_result(user_id, payload, db)
    return result.model_dump(mode="json")


async def _exec_save_memory(user_id: UUID, params: dict, db: asyncpg.Connection) -> dict:
    summary = params["summary"]
    await _save_memory_to_vector(user_id, summary, _db._pool)
    return {"summary": summary}


async def _exec_update_safety_plan(user_id: UUID, params: dict, db: asyncpg.Connection) -> dict:
    payload = SafetyPlanUpsert(**params)
    result = await support_service.save_safety_plan(user_id, payload, db)
    return result.model_dump(mode="json")


ACTION_DISPATCH = {
    "record_mood": _exec_record_mood,
    "create_micro_action": _exec_create_micro_action,
    "update_action_status": _exec_update_action_status,
    "schedule_checkin": _exec_schedule_checkin,
    "record_coping_result": _exec_record_coping_result,
    "save_memory": _exec_save_memory,
    "update_safety_plan": _exec_update_safety_plan,
}
