from uuid import UUID

import asyncpg

CRITICAL_KEYWORDS: list[str] = [
    "想自杀", "要自杀", "去自杀",
    "想死", "要死了", "不想活",
    "结束生命", "结束自己", "已经自己",
    "跳楼", "跳河", "上吊", "割腕", "窒息",
    "买好了药", "拿好了药", "准备好了",
    "从此就结束", "今天就结束", "马上就",
    "遗书",
]

HOTLINE_APPEND = (
    "\n\n……对了，我想让你知道一件事——"
    "北京心理危机研究与干预中心的电话是 010-82951332，24 小时都有人接。"
    "你任何时候想打就打，多晚也完全没关系。我在这里陪着你，好吗？"
)


def find_matched_keyword(text: str) -> str | None:
    """返回第一个命中的危机关键词；没命中返回 None。

    单独抽出来，一是让 check_and_append_hotline 能同时报告"命中了没有"
    和"具体命中哪个词"而不用重复扫两遍，二是方便直接测试"命中的是哪个词"
    这件事本身，不用每次都拐弯去测 check_and_append_hotline 的副作用。
    """
    for kw in CRITICAL_KEYWORDS:
        if kw in text:
            return kw
    return None


def check_and_append_hotline(user_message: str, ai_response: str) -> tuple[str, bool, str | None]:
    """检查用户消息是否命中危机关键词，若命中则在 AI 响应末尾追加热线提示。

    返回 (最终响应, 是否触发, 命中的关键词——没触发时是 None)
    """
    matched = find_matched_keyword(user_message)
    if matched:
        return ai_response + HOTLINE_APPEND, True, matched
    return ai_response, False, None


async def save_crisis_event(
    user_id: UUID,
    message_id: UUID | None,
    matched_keyword: str,
    db: asyncpg.Connection,
) -> None:
    """把命中的危机事件记进 crisis_events——审计用，回答哪些用户、多少次、
    命中了哪个关键词，跟真正的对话内容分开存，不是给 Agent 读取用的。
    """
    await db.execute(
        "INSERT INTO crisis_events (user_id, message_id, matched_keyword) VALUES ($1, $2, $3)",
        user_id, message_id, matched_keyword,
    )
