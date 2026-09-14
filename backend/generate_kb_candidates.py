"""挖 lookup_logs 里"本地知识库没覆盖到、但被真实问过"的问题，只从可信来源
（app/agent/rag.py 的 TRUSTED_DOMAINS 白名单）搜集原始资料，起草候选知识库
词条，存成候选文件供人工审核——不直接写库。

跟 v1 的区别：
  - 不可信来源的搜索结果直接丢弃，不进候选；
  - 正文由原始资料片段拼接而成，LLM 只负责起标题、提取关键词，不做自由改写；
  - 每条候选都会先跑一遍自动检查（来源可信度/完整性/查重/可追溯性/时效性），
    结果存进候选文件的 checks 字段，供人工审核时参考；
  - 重新跑这个脚本不会覆盖已经在候选文件里的问题（包括更早、旧格式挖到的），
    只会追加新挖到的。

用法：
    cd backend
    python generate_kb_candidates.py

跑完之后：打开 app/knowledge/kb_candidates.json 人工审核。注意 approved
只是"人工认可"，不能绕过自动检查——只有 checks.all_passed 为 true 且
approved 为 true 的候选，approve_kb_candidates.py 才会真正写库。
"""
import asyncio
import io
import json
import sys

if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8")

from pathlib import Path

import app.database as _db
from app.agent.llm import get_llm
from app.agent.rag import search_raw
from app.services.kb_candidate_service import (
    assemble_candidate_content,
    build_classification_prompt,
    fetch_kb_contents,
    fetch_uncovered_queries,
    filter_trusted_results,
    group_uncovered_queries,
    merge_candidates,
    parse_classification_response,
    run_automated_checks,
)

OUT_FILE = Path("app/knowledge/kb_candidates.json")


async def main():
    existing: list[dict] = []
    if OUT_FILE.exists():
        existing = json.loads(OUT_FILE.read_text(encoding="utf-8"))
        print(f"候选文件已存在 {len(existing)} 条（含旧格式/已审核的，不会被覆盖）")

    existing_keys = {c["query_text"].strip().lower() for c in existing if c.get("query_text")}

    await _db.init_pool()
    try:
        rows = await fetch_uncovered_queries(_db._pool)
        print(f"lookup_logs 里 source=web 的记录共 {len(rows)} 条")

        groups = group_uncovered_queries(rows, min_count=1)
        groups = [g for g in groups if g["query_text"].strip().lower() not in existing_keys]
        print(f"聚合后、排除已在候选文件里的问题，剩 {len(groups)} 个新问题\n")

        if not groups:
            print("没有新候选，不用生成任何东西。")
            return

        kb_texts = await fetch_kb_contents(_db._pool)
        llm = get_llm()
        new_candidates = []

        for i, g in enumerate(groups, 1):
            query = g["query_text"]
            print(f"  [{i}/{len(groups)}] 起草：{query}（出现 {g['count']} 次）")

            try:
                # 用 google 引擎，不用默认的 baidu：baidu 引擎返回的 link 是
                # baidu 自己的跳转包装链接（baidu.com/link?url=...），真实域名
                # 被包在参数里，filter_trusted_results 的域名硬过滤永远匹配不上；
                # google 引擎返回的才是可信来源的真实 URL（用真实数据验证过：
                # 同样的查询词，baidu 引擎命中 0 条可信来源，google 引擎能命中
                # dxy.com/mayoclinic.org/who.int）。
                organic = await search_raw(query, engine="google")
            except Exception as e:
                print(f"      搜索失败，跳过：{e}")
                continue

            segments = filter_trusted_results(organic)
            if not segments:
                print("      没有命中任何可信来源，跳过（不从不可信来源起草候选）")
                continue

            try:
                prompt = build_classification_prompt(query, segments)
                response = await llm.ainvoke(prompt)
                parsed = parse_classification_response(response.content)
            except Exception as e:
                print(f"      分类/关键词提取失败，跳过：{e}")
                continue

            if parsed is None:
                print("      解析失败，跳过")
                continue

            content = assemble_candidate_content(segments)
            candidate = {
                "query_text": query,
                "count": g["count"],
                "topic": "auto_mined",
                "title": parsed["title"],
                "keywords": parsed["keywords"],
                "segments": segments,
                "content": content,
                "source": "网络搜索（可信来源，原文片段未改写）",
                "approved": False,
                "inserted_at": None,
            }
            checks = run_automated_checks(candidate, kb_texts)
            candidate["checks"] = checks
            status = "✓ 自动检查全部通过" if checks["all_passed"] else "✗ 未通过自动检查，需人工留意"
            print(f"      {status}")
            new_candidates.append(candidate)

        merged = merge_candidates(existing, new_candidates)
        OUT_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        passed = sum(1 for c in new_candidates if c.get("checks", {}).get("all_passed"))
        print(f"\n候选词条已保存到 {OUT_FILE.resolve()}")
        print(f"本次新增 {len(new_candidates)} 条（其中 {passed} 条自动检查全部通过），文件总计 {len(merged)} 条")
        print("下一步：打开这个文件人工审核，把想采纳的条目的 approved 改成 true，")
        print("改完再跑 python approve_kb_candidates.py——但只有自动检查也通过的候选才会真正写库。")
    finally:
        await _db.close_pool()


asyncio.run(main())
