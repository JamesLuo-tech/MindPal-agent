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

# 危机判断只靠关键词字面匹配是不够的——换一种说法、委婉/间接表达
# （"如果哪天我不在了""不用担心我了""东西都交代好了"这类）都不会命中
# 任何关键词，但语义上确实是危机信号。审计日志里用这个占位标识区分
# "关键词命中"和"LLM 单独判断出来"，不是真的关键词原文。
LLM_DETECTED_LABEL = "[llm-detected]"

HOTLINE_APPEND = (
    "\n\n……对了，我想让你知道一件事——"
    "北京心理危机研究与干预中心的电话是 010-82951332，24 小时都有人接。"
    "你任何时候想打就打，多晚也完全没关系。我在这里陪着你，好吗？"
)

_CRISIS_CLASSIFY_PROMPT = (
    "判断用户这句话有没有透露出自杀/自伤/想要结束生命的风险信号。不要只看有没有"
    "明确说\"自杀\"\"想死\"这类词，也要看有没有间接、委婉、隐晦的表达——比如"
    "\"不想再撑下去了\"\"如果哪天我不在了\"\"东西都交代好了\"\"解脱了\""
    "\"不用担心我了\"这类。只判断用户是不是在说自己，不是在说别人、电影、新闻、"
    "过去已经过去的事。\n\n"
    "这是心理健康场景，漏判的代价远大于误判——拿不准的时候，宁可判断为"
    "\"有风险\"，不要因为表达委婉、信息不够确定就放过。\n\n"
    "用户消息：{text}\n\n"
    "只回答一个词：有风险 / 没有风险"
)


def find_matched_keyword(text: str) -> str | None:
    """返回第一个命中的危机关键词；没命中返回 None。

    单独抽出来，一是让 append_hotline_if_triggered 之外的调用方也能report
    "命中了没有"和"具体命中哪个词"而不用重复扫两遍，二是方便直接测试
    "命中的是哪个词"这件事本身。
    """
    for kw in CRITICAL_KEYWORDS:
        if kw in text:
            return kw
    return None


def build_crisis_classification_prompt(text: str) -> str:
    """纯函数，方便不起 LLM 就测 prompt 拼接对不对。"""
    return _CRISIS_CLASSIFY_PROMPT.format(text=text)


def parse_crisis_classification(content: str) -> bool:
    """解析第二层 LLM 的风险判断。注意"有风险"是"没有风险"的子串，不能
    直接用 in 判断，要先排除"没有风险"这种否定表达。格式不对/解析不出来
    时保守判断为"有风险"——这里的默认值跟其他"格式不对就保守拒绝"的
    地方（比如 RAG relevance grading）刻意反过来：那边漏判的代价是"多
    转一次网络搜索"，这里漏判的代价可能是真的没接住一个有危险的人，
    两者的风险不对称，所以默认值也应该不一样。
    """
    text = content.strip()
    if "没有风险" in text or "没风险" in text or "不认为" in text:
        return False
    if "有风险" in text:
        return True
    return True  # 完全没按格式回答——保守起见还是当作有风险处理


async def classify_crisis_risk(text: str, llm) -> bool:
    """第二层：LLM 语义判断，补关键词匹配的召回盲区。

    这里的失败处理跟上面 parse 函数的"格式不对就保守判断为有风险"刻意不
    对称：LLM 调用本身失败（网络错误、超时、限流……）是基础设施问题，
    跟这句话有没有危机信号无关——如果因为一次 API 抖动就让"调用失败"
    也判成"有风险"，等于把每一次 LLM 故障都变成一次假警报风暴（安全计划
    误加载、热线文案误追加、审计日志里全是噪音）。真正兜底的是第一层
    关键词匹配：它不依赖 LLM 是否可用，第二层挂了，关键词命中的场景依然
    会被正确处理，只是丧失了"补召回盲区"这个增量能力，不是丧失了底线。
    """
    try:
        prompt = build_crisis_classification_prompt(text)
        response = await llm.bind(temperature=0).ainvoke(prompt)
        return parse_crisis_classification(response.content)
    except Exception as e:
        print(f"[WARN] 危机二层 LLM 判断失败，本轮跳过语义判断（第一层关键词匹配仍然生效）: {e}")
        return False


async def assess_crisis(user_message: str, llm) -> tuple[bool, str | None]:
    """统一的危机判断入口：两层信号取"或"——关键词命中，或者关键词没命中
    但 LLM 语义判断认为有风险，只要有一个说"是"就判定为触发。LLM 只增加
    判断为"有风险"的机会，不会推翻关键词已经命中的判断，也不会在关键词
    已经命中时再多花一次 LLM 调用去"确认"——两层不是"层层加码更严格"，
    是"关键词负责兜底、LLM 负责扩大召回"。

    返回 (是否触发危机处理, 用于审计日志的标识)：命中关键词时是关键词
    原文，LLM 单独判断出来时是 LLM_DETECTED_LABEL 占位标识，都没触发时
    是 None。
    """
    matched_keyword = find_matched_keyword(user_message)
    if matched_keyword is not None:
        return True, matched_keyword

    llm_flagged = await classify_crisis_risk(user_message, llm)
    return llm_flagged, (LLM_DETECTED_LABEL if llm_flagged else None)


def append_hotline_if_triggered(ai_response: str, triggered: bool) -> str:
    """危机判断已经在别处（assess_crisis）做完了，这里只负责"触发了就把
    热线文案追加到回复末尾"这一步本身，不重复做判断——避免同一轮对话里
    "要不要触发"这件事被两个不同的地方（一个两层判断、一个只看关键词）
    各自独立决定，得出不一致的结果。
    """
    if triggered:
        return ai_response + HOTLINE_APPEND
    return ai_response


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
