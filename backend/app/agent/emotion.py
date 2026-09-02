"""每轮对话结束后异步提取情绪标签，写入 emotions 表。"""
from __future__ import annotations

import json
import re
from uuid import UUID

import asyncpg
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

_EXTRACTION_PROMPT = """\
从以下对话中提取用户的情绪状态，只输出 JSON，不要有任何其他文字。

对话内容：
用户：{user_message}
MindPal：{ai_response}

输出格式：
{{
  "primary_emotion": "主要情绪，从以下选一个：悲伤/焦虑/愤怒/恐惧/无助/孤独/疲惫/平静/希望/麻木/其他",
  "secondary_emotions": ["次要情绪列表，可为空数组"],
  "intensity": 情绪强度整数1到10,
  "triggers": ["触发因素列表，可为空数组"]
}}"""

_DEFAULT_EMOTION: dict = {
    "primary_emotion": "其他",
    "secondary_emotions": [],
    "intensity": 5,
    "triggers": [],
}


def _parse_json(text: str) -> dict:
    """容错解析 LLM 响应中的 JSON，处理 markdown 代码块包装。"""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


async def extract_emotion(
    user_message: str,
    ai_response: str,
    llm: ChatOpenAI,
) -> dict:
    """调用 LLM 从对话中提取情绪标签，解析或调用失败时返回默认值。"""
    prompt = _EXTRACTION_PROMPT.format(
        user_message=user_message[:300],
        ai_response=ai_response[:300],
    )
    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        data = _parse_json(response.content)
        return {
            "primary_emotion": str(data.get("primary_emotion", "其他"))[:32],
            "secondary_emotions": list(data.get("secondary_emotions") or []),
            "intensity": max(1, min(10, int(data.get("intensity", 5)))),
            "triggers": list(data.get("triggers") or []),
        }
    except Exception:
        return _DEFAULT_EMOTION.copy()


async def save_emotion(
    user_id: UUID,
    message_id: UUID,
    emotion_data: dict,
    db: asyncpg.Connection,
) -> None:
    """将情绪数据写入 emotions 表。"""
    await db.execute(
        """
        INSERT INTO emotions
            (user_id, message_id, primary_emotion, secondary_emotions, intensity, triggers)
        VALUES ($1, $2, $3, $4::jsonb, $5, $6::jsonb)
        """,
        user_id,
        message_id,
        emotion_data["primary_emotion"],
        emotion_data["secondary_emotions"],
        emotion_data["intensity"],
        emotion_data["triggers"],
    )
