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


def check_and_append_hotline(user_message: str, ai_response: str) -> tuple[str, bool]:
    """检查用户消息是否命中危机关键词，若命中则在 AI 响应末尾追加热线提示。

    返回 (最终响应, 是否触发)
    """
    for kw in CRITICAL_KEYWORDS:
        if kw in user_message:
            return ai_response + HOTLINE_APPEND, True
    return ai_response, False
