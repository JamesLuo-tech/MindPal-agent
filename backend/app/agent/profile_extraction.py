"""从对话里被动提取"值得长期记住的用户资料"——昵称/年龄段/诊断这类稳定的
个人信息，以及值得记住的重要事件（换工作、分手、开始/停止吃药这类）。

这是被动提取，不是用户主动要求记录的写入动作——跟 propose_* 这类"提议-
确认"工具是两回事：这里提取的是低风险的个性化信息（不触发任何行为、只是
让下一轮对话更懂你），不需要用户逐条确认，就像情绪提取（emotion.py）一样
是后台静默完成的，写入 user_profiles/key_events 这两张之前完全没有写入
路径的表。

跟情绪提取分开一次 LLM 调用、分开一个模块，是因为两者的提示词目标不
一样，混在一个 prompt 里容易两边都做不好。
"""
from __future__ import annotations

import json
from uuid import UUID

import asyncpg

_EXTRACTION_PROMPT = """分析这轮对话，看有没有以下两类值得长期记住的信息：

1. 用户的稳定个人资料——昵称、年龄段、确诊过的诊断/状况。只在用户明确
   提到这些具体信息时才提取，不要猜测或者从语气推断。
2. 一件对用户来说比较重要的事件——比如换工作、分手、开始/停止吃药、
   搬家、重大人际冲突这类会持续影响状态的事，不是日常小事（"今天很累"
   这种不算）。

用户：{user_message}
AI：{ai_response}

按下面的 JSON 格式输出，没有提取到的字段填 null，不要输出其他任何内容：
{{"nickname": null, "age_range": null, "diagnosis": null, "key_event": null}}

如果有重要事件，"key_event" 填成这样的对象（不是字符串）：
{{"event_type": "简短分类，比如 relationship/work/medication/other", "content": "一句话描述", "importance": 1到10的整数}}
"""


def parse_profile_extraction(content: str) -> dict:
    """解析提取结果。解析失败/格式不对时返回全空的结果，不抛异常——
    这是后台静默任务，出错不该影响主流程，也不该硬凑一条错误数据。
    """
    empty = {"nickname": None, "age_range": None, "diagnosis": None, "key_event": None}
    try:
        data = json.loads(content.strip())
    except (json.JSONDecodeError, TypeError):
        return empty

    if not isinstance(data, dict):
        return empty

    result = dict(empty)
    for key in ("nickname", "age_range", "diagnosis"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value.strip()

    event = data.get("key_event")
    if isinstance(event, dict) and str(event.get("content") or "").strip():
        importance = event.get("importance", 5)
        if not isinstance(importance, int) or not (1 <= importance <= 10):
            importance = 5
        result["key_event"] = {
            "event_type": str(event.get("event_type") or "other")[:32],
            "content": str(event["content"]).strip(),
            "importance": importance,
        }
    return result


async def extract_profile_info(user_message: str, ai_response: str, llm) -> dict:
    """跑一次提取，返回结构化结果——不碰数据库，纯提取逻辑，方便测试。"""
    prompt = _EXTRACTION_PROMPT.format(user_message=user_message, ai_response=ai_response)
    response = await llm.ainvoke(prompt)
    return parse_profile_extraction(response.content)


async def save_profile_updates(user_id: UUID, updates: dict, db: asyncpg.Connection) -> None:
    """把 nickname/age_range/diagnosis 里非空的字段 upsert 进 user_profiles。

    用 COALESCE 保留没提到的字段原值——不会因为这一轮只提到了昵称，
    就把之前记过的诊断信息覆盖成空。三个字段都没提取到时直接跳过，
    不发一次空更新。
    """
    if not any(updates.get(k) for k in ("nickname", "age_range", "diagnosis")):
        return
    await db.execute(
        """
        INSERT INTO user_profiles (user_id, nickname, age_range, diagnosis)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (user_id) DO UPDATE SET
            nickname = COALESCE(EXCLUDED.nickname, user_profiles.nickname),
            age_range = COALESCE(EXCLUDED.age_range, user_profiles.age_range),
            diagnosis = COALESCE(EXCLUDED.diagnosis, user_profiles.diagnosis),
            updated_at = NOW()
        """,
        user_id, updates.get("nickname"), updates.get("age_range"), updates.get("diagnosis"),
    )


async def save_key_event(user_id: UUID, event: dict, db: asyncpg.Connection) -> None:
    """把提取到的重要事件写进 key_events，供 load_long_term 之后按重要度取用。"""
    await db.execute(
        "INSERT INTO key_events (user_id, event_type, content, importance) VALUES ($1, $2, $3, $4)",
        user_id, event["event_type"], event["content"], event["importance"],
    )
