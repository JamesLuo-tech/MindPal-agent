"""从 lookup_logs 里挖"本地知识库没覆盖到、但被真实问过"的话题，起草候选知识库
词条，供人工审核后再决定要不要真的收进 knowledge_base。

跟 v1（自由改写版）的区别——按用户给的企业级设计重做：

  1. 限制资料来源：只从 rag.py 里 TRUSTED_DOMAINS 白名单域名采集资料，
     不在名单内的搜索结果直接丢弃（不是排后面，是根本不进入候选）；
     保留每条资料的原文片段、网址、发布日期，不做自由改写——LLM 只负责
     给这些原文起标题、提取关键词，正文由原文片段拼接而成，不是模型现编的。
  2. 自动检查，不满足条件就暂不入库：来源可信度、内容完整性、查重、
     "正文能不能追溯回原文"、时效性——五项检查全部通过才允许真正写入
     knowledge_base；检查不通过就留在候选区，正式知识库继续用原有内容，
     不会因为"没人审核"就被动收录一条不确定的内容（默认排除，而不是
     默认收录）。人工 approved=true 只是"我认可这条候选"，不能绕过自动检查——
     两者是 AND 的关系，不是"人工说了算"。

跟 propose_* 写入工具是同一套"提议-确认"安全模型的延伸：这里多了一层
"连人工确认都不能绕过的自动化校验"，因为知识库内容会被所有用户看到，
风险比某一个用户自己的 propose_* 写入更高。
"""
from __future__ import annotations

import difflib
import re
from datetime import datetime, timezone

import asyncpg

from app.agent.rag import TRUSTED_DOMAINS

# ---------------------------------------------------------------------------
# 1. 聚合 lookup_logs 里的未覆盖问题（跟 v1 一样，没有变化）
# ---------------------------------------------------------------------------


def group_uncovered_queries(rows: list[dict], min_count: int = 1) -> list[dict]:
    """把 lookup_logs 里 source='web' 的记录按问题原文（去首尾空格、忽略大小写）
    聚合，返回出现次数 >= min_count 的分组，按次数从高到低排序。

    纯函数，不连数据库，好测。注意这只是精确字符串匹配，同一个意图换种
    说法问不会被聚到一起——真要做语义聚类需要再接一次 embedding 相似度分组，
    数据量小的时候没必要为了几条数据先上更复杂的逻辑。
    """
    groups: dict[str, dict] = {}
    for row in rows:
        key = row["query"].strip().lower()
        if not key:
            continue
        if key not in groups:
            groups[key] = {"query_text": row["query"].strip(), "count": 0, "log_ids": []}
        groups[key]["count"] += 1
        groups[key]["log_ids"].append(str(row["id"]))

    result = [g for g in groups.values() if g["count"] >= min_count]
    result.sort(key=lambda g: g["count"], reverse=True)
    return result


# ---------------------------------------------------------------------------
# 2. 限制资料来源：硬过滤可信域名，保留原文片段 + 出处
# ---------------------------------------------------------------------------


def filter_trusted_results(organic_results: list[dict], max_results: int = 3) -> list[dict]:
    """从 SerpAPI 原始 organic_results 里硬过滤出可信来源的结果，转成
    统一的 segment 结构。不在 TRUSTED_DOMAINS 里的结果直接丢弃——这跟
    rag.py 的 web_search() 不一样，web_search 只是把可信来源排到前面，
    仍然会把不可信来源的内容喂给聊天 LLM；知识库是所有用户共享的长期
    资产，标准要更严，不可信来源根本不应该进入候选。

    每个 segment 保留原文（snippet，不改写）、来源网址、来源域名、
    发布日期（SerpAPI 不一定给，没有就是 None）——这些字段就是后面
    自动检查和"追溯到原文"的依据。
    """
    kept: list[dict] = []
    for r in organic_results:
        link = r.get("link", "")
        domain = next((d for d in TRUSTED_DOMAINS if d in link), None)
        if domain is None:
            continue
        snippet = (r.get("snippet") or "").strip()
        if not snippet:
            continue
        kept.append({
            "text": snippet,
            "source_url": link,
            "source_domain": r.get("displayed_link") or domain,
            "published_date": r.get("date"),
        })
        if len(kept) >= max_results:
            break
    return kept


def assemble_candidate_content(segments: list[dict]) -> str:
    """正文由原文片段直接拼接而成，每段后面附上出处——不是 LLM 自由生成的
    叙述。这样"正文里的每句话都能找到对应原文"是结构上保证的，不用指望
    模型自觉不瞎编。"""
    parts = []
    for s in segments:
        date_str = s.get("published_date") or "发布日期未知"
        parts.append(f"{s['text']}\n（来源：{s['source_domain']}，{date_str}，{s['source_url']}）")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# 3. LLM 只做分类 + 关键词提取，不做正文改写
# ---------------------------------------------------------------------------

_KB_CLASSIFY_PROMPT = (
    "下面是几段从可信来源搜到的、关于同一个用户问题的原始资料片段（已经是原文，"
    "不需要你改写内容，也不要总结或复述）。请你只做两件事：\n"
    "1. 给这些资料整体起一个简洁的标题，一句话概括这是关于什么问题的；\n"
    "2. 提取 3-5 个关键词，方便后续检索归类。\n"
    "不要添加资料里没有的判断或结论。\n\n"
    "用户问题：{query}\n\n"
    "原始资料片段：\n{segments_text}\n\n"
    "请按下面的格式输出（不要加多余的解释）：\n"
    "标题: <一句话>\n"
    "关键词: <关键词1>、<关键词2>、<关键词3>"
)


def build_classification_prompt(query: str, segments: list[dict]) -> str:
    """纯函数，方便不起 LLM 就测 prompt 拼接对不对。"""
    segments_text = "\n\n".join(
        f"[来源 {i + 1}: {s['source_domain']}] {s['text']}" for i, s in enumerate(segments)
    )
    return _KB_CLASSIFY_PROMPT.format(query=query, segments_text=segments_text)


def parse_classification_response(content: str) -> dict | None:
    """解析 LLM 给的标题 + 关键词，跟 v1 的 parse_kb_draft_response 不一样——
    这里不解析"正文"，因为正文不该由模型生成，只由 assemble_candidate_content
    拼原文得到。没有标题就返回 None，让调用方跳过这条。"""
    title = None
    keywords: list[str] = []
    for line in content.strip().split("\n"):
        if line.startswith("标题:") or line.startswith("标题："):
            title = line.split(":", 1)[-1].split("：", 1)[-1].strip()
        elif line.startswith("关键词:") or line.startswith("关键词："):
            raw = line.split(":", 1)[-1].split("：", 1)[-1].strip()
            keywords = [k.strip() for k in re.split("[、,，]", raw) if k.strip()]

    if not title:
        return None
    return {"title": title, "keywords": keywords}


# ---------------------------------------------------------------------------
# 4. 自动检查——五项都通过才允许入库，跟人工 approved 是 AND 的关系
# ---------------------------------------------------------------------------


def check_source_trust(segments: list[dict]) -> dict:
    """每条原始资料必须来自允许列表里的域名，有网址、有非空原文。"""
    if not segments:
        return {"passed": False, "detail": "没有命中任何可信来源的原始资料"}
    for seg in segments:
        domain = seg.get("source_domain", "")
        if not any(d in domain for d in TRUSTED_DOMAINS):
            return {"passed": False, "detail": f"来源域名「{domain}」不在允许列表内"}
        if not seg.get("source_url"):
            return {"passed": False, "detail": "有资料缺少来源网址"}
        if not (seg.get("text") or "").strip():
            return {"passed": False, "detail": "有资料原文为空"}
    return {"passed": True, "detail": f"{len(segments)} 条资料均来自可信来源，原文完整"}


def check_completeness(segments: list[dict], min_chars: int = 20) -> dict:
    """原文片段长度不能太短——太短通常是搜索引擎摘要被截断，信息不完整，
    不足以支撑一条知识条目。"""
    short = [s for s in segments if len(s.get("text", "").strip()) < min_chars]
    if short:
        return {
            "passed": False,
            "detail": f"有 {len(short)} 条原文片段短于 {min_chars} 字，可能被截断，信息不完整",
        }
    return {"passed": True, "detail": "原文片段长度均达标"}


def check_duplicate(candidate_text: str, existing_kb_texts: list[str], threshold: float = 0.85) -> dict:
    """跟现有知识库内容比对文本相似度，超过阈值判定为疑似重复。用标准库
    difflib 做字符级相似度，不依赖 embedding——足够当一道"防止一模一样的
    内容被重复收录"的检查，不追求语义级查重（语义查重可以用向量相似度做
    进一步升级，但那需要连数据库/编码模型，这里保持纯函数、方便单测）。
    """
    for existing in existing_kb_texts:
        ratio = difflib.SequenceMatcher(None, candidate_text, existing).ratio()
        if ratio >= threshold:
            return {"passed": False, "detail": f"与现有知识库内容高度相似（相似度 {ratio:.2f}），疑似重复"}
    return {"passed": True, "detail": "未发现与现有知识库高度重复的内容"}


def check_claim_traceability(content: str, segments: list[dict]) -> dict:
    """正文里的每一段都必须能在某条原始资料里原样找到——因为正文本来就是
    由 assemble_candidate_content 拼原文得到的，这项检查理论上必然通过；
    留着是为了防御性地拦住"以后有人改代码，不小心又把 LLM 自由生成的文本
    塞进 content"这种回归，而不是去做语义层面的"这句话有没有依据"判断
    （那件事本质上还是要靠模型去理解，模型自己说"对"不能当证据，这点
    应该用别的机制解决，不能指望这条检查函数）。"""
    for seg in segments:
        text = seg.get("text", "").strip()
        if text and text not in content:
            return {"passed": False, "detail": "正文中存在无法对应到任何原始资料的内容"}
    return {"passed": True, "detail": "正文中的每一段都能追溯到对应的原始资料"}


def check_staleness(segments: list[dict], stale_days: int = 730, now: datetime | None = None) -> dict:
    """检查来源的发布日期：超过 stale_days（默认 2 年）判定为可能过时；
    所有来源都没有可用日期时，保守起见也不自动放行（无法判断新旧，不能
    默认它是新的）。"""
    now = now or datetime.now(timezone.utc)
    stale = []
    unknown = 0
    for seg in segments:
        date_str = seg.get("published_date")
        if not date_str:
            unknown += 1
            continue
        try:
            d = datetime.fromisoformat(date_str)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
        except ValueError:
            unknown += 1
            continue
        if (now - d).days > stale_days:
            stale.append(seg.get("source_url"))

    if stale:
        return {"passed": False, "detail": f"{len(stale)} 条来源发布日期超过 {stale_days} 天，可能已过时"}
    if unknown == len(segments):
        return {"passed": False, "detail": "所有来源都没有可用的发布日期，无法判断时效性，保守起见先不自动放行"}
    return {"passed": True, "detail": "来源时效性检查通过"}


def run_automated_checks(candidate: dict, existing_kb_texts: list[str]) -> dict:
    """跑齐五项自动检查，返回每项结果 + 总的 all_passed。

    注意：这里特意不引入"另一个模型来交叉检查"这条路径——即使加了，两个
    模型都说"没问题"也不构成事实证明，容易造成一种虚假的确定感。上面五项
    都是可复现、可解释、不依赖模型自我报告的规则检查，这才是能真正拦事的
    东西；语义层面的"内容是否与现有知识冲突"没有可靠的自动化手段，所以
    没有单独做一个"冲突检测"项，而是通过查重 + 时效性这两项做力所能及的
    覆盖，冲突判断最终还是要留给人工审核。
    """
    segments = candidate.get("segments", [])
    content = candidate.get("content", "")
    checks = {
        "source_trust": check_source_trust(segments),
        "completeness": check_completeness(segments),
        "dedup": check_duplicate(content, existing_kb_texts),
        "claim_traceability": check_claim_traceability(content, segments),
        "staleness": check_staleness(segments),
    }
    checks["all_passed"] = all(c["passed"] for c in checks.values())
    return checks


# ---------------------------------------------------------------------------
# 5. 候选文件合并——重新跑生成脚本不能覆盖掉已经存在的候选（包括旧格式的）
# ---------------------------------------------------------------------------


def merge_candidates(existing: list[dict], new_candidates: list[dict]) -> list[dict]:
    """已经在候选文件里的问题（不管是旧格式还是新格式、人工看没看过）原样
    保留，只把文件里还没出现过的问题追加进去。避免重复跑生成脚本时把人工
    已经审核/标记过的候选静默覆盖掉。"""
    existing_keys = {c["query_text"].strip().lower() for c in existing if c.get("query_text")}
    appended = [c for c in new_candidates if c["query_text"].strip().lower() not in existing_keys]
    return existing + appended


# ---------------------------------------------------------------------------
# 6. 数据库读写
# ---------------------------------------------------------------------------


async def fetch_uncovered_queries(pool: asyncpg.Pool, since=None) -> list[dict]:
    """查 lookup_logs 里所有走了网络兜底的记录（本地知识库没覆盖到的问题）。"""
    query = "SELECT id, query, created_at FROM lookup_logs WHERE source = 'web'"
    params: list = []
    if since is not None:
        query += " AND created_at >= $1"
        params.append(since)
    query += " ORDER BY created_at DESC"

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
    return [dict(r) for r in rows]


async def fetch_kb_contents(pool: asyncpg.Pool) -> list[str]:
    """取现有知识库全部正文，供查重检查比对。"""
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT content FROM knowledge_base WHERE is_active = TRUE")
    return [r["content"] for r in rows]


async def insert_approved_candidate(
    pool: asyncpg.Pool,
    topic: str,
    title: str,
    content: str,
    source: str,
    source_url: str | None = None,
    quality_score: float = 0.8,
) -> str:
    """人工确认 + 自动检查都通过的候选词条，真正写进 knowledge_base——只有
    这一步执行完，内容才会被检索到。quality_score 默认给 0.8，比种子文档的
    0.9+ 略低，标记这是自动挖掘 + 人工审核的内容，不是最初精心整理的那批
    种子数据。source_url 取第一条原始资料的网址，供后续追溯。"""
    from app.agent.rag import _encode

    vec = await _encode(f"{title}\n\n{content}")
    async with pool.acquire() as conn:
        row_id = await conn.fetchval(
            """
            INSERT INTO knowledge_base (topic, title, content, source, source_url, embedding, quality_score)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
            """,
            topic, title, content, source, source_url, vec, quality_score,
        )
    return str(row_id)
