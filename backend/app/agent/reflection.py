"""对话结束后的反思——不进图、不进 SSE 流程，完全在后台跑，跟情绪提取
（emotion.py + chat_service._emotion_background）是同一种"这一轮结束后
顺手做点额外分析"的模式，不影响这一轮的流式体验。

只检查三件事（都是这个项目里真实关心的风险点，不是泛泛的"回答好不好"）：
  1. 危机场景下语气对不对——只在 crisis_triggered=True 时检查
  2. 人设有没有跑偏——每轮都检查
  3. 多意图合并后有没有漏掉某个分段该有的内容——只在这轮是多意图时检查

发现问题时生成一句具体的自我提醒，存进 Redis（memory.save_reflection_note），
下一轮对话开始时读出来注入 prompt；本轮已经发出去的回复不会被改，
优化的是"接下来"，不是"刚才"。
"""
from __future__ import annotations

_REFLECTION_PROMPT_HEADER = (
    "你是在复盘 MindPal（一个心理陪伴 AI，人设是懂事、说话像朋友/发小，"
    "不端着、不说教、不给医疗诊断）刚才这一轮的回复，看有没有问题，"
    "帮它下一轮说得更好。只看下面明确列出的检查项，不要吹毛求疵地挑无关的毛病。\n\n"
    f"用户这轮说：{{user_message}}\n"
    f"MindPal 回复：{{final_response}}\n\n"
    "检查项：\n"
    "1.【人设】这条回复有没有变得像说明书/心理咨询模板/说教（比如"
    "\"你应该...\"\"建议你...\"这类生硬建议），而不是朋友聊天的语气？\n"
)

_CRISIS_CHECK_ITEM = (
    "2.【危机语气】用户这轮的话被判断为危机时刻，回复有没有真的接住情绪，"
    "而不是生硬地念安全计划条目、或者轻飘飘地一带而过？\n"
)

_MULTI_INTENT_CHECK_ITEM = (
    "3.【多意图完整性】用户这轮其实说了两件事，下面是分别针对每件事生成的"
    "原始草稿，最终回复有没有把其中一件事的实际内容漏掉？\n"
    "原始草稿：\n{drafts}\n"
)

_REFLECTION_PROMPT_FOOTER = (
    "\n如果检查项都没问题，只回复 OK。\n"
    "如果发现问题，回复\"问题: \"后面跟一句话，具体说清楚下次遇到类似情况要注意什么"
    "（这句话会被直接放进下一轮对话的 prompt 里，所以要写得像一条给 AI 自己看的提醒，"
    "不是写给用户看的）。"
)


def build_reflection_prompt(
    user_message: str,
    final_response: str,
    crisis_triggered: bool,
    segment_drafts: list[dict] | None,
) -> str:
    """纯函数，方便不起 LLM 就测 prompt 拼接对不对（该不该带上某个检查项）。"""
    parts = [_REFLECTION_PROMPT_HEADER.format(user_message=user_message, final_response=final_response)]
    if crisis_triggered:
        parts.append(_CRISIS_CHECK_ITEM)
    if segment_drafts:
        drafts_text = "\n".join(f"- [{d['agent_type']}] {d['text']}" for d in segment_drafts)
        parts.append(_MULTI_INTENT_CHECK_ITEM.format(drafts=drafts_text))
    parts.append(_REFLECTION_PROMPT_FOOTER)
    return "".join(parts)


def parse_reflection_response(content: str) -> str | None:
    """解析反思 LLM 的回复。"OK"（或者任何没有按格式说明问题的输出）都当作
    没发现问题处理——宁可漏掉一些真实问题，也不要因为解析太宽松，把无关的话
    当成"问题"存进 Redis 污染下一轮的 prompt。"""
    text = content.strip()
    if text.upper().startswith("OK"):
        return None
    if text.startswith("问题"):
        # 支持"问题:"和"问题："两种冒号
        note = text.split(":", 1)[-1].split("：", 1)[-1].strip()
        return note or None
    return None


async def reflect_on_turn(
    user_message: str,
    final_response: str,
    crisis_triggered: bool,
    segment_drafts: list[dict] | None,
    llm,
) -> str | None:
    """跑一次反思，返回自我提醒文本；没发现问题返回 None。

    调用方（chat_service._reflection_background）负责把结果存进 Redis，
    这里只做"判断"，不碰存储——保持这个函数纯粹、好测试。
    """
    prompt = build_reflection_prompt(user_message, final_response, crisis_triggered, segment_drafts)
    response = await llm.ainvoke(prompt)
    return parse_reflection_response(response.content)
