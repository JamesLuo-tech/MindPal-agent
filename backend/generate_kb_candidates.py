"""挖 lookup_logs 里"本地知识库没覆盖到、但被真实问过"的问题，用真实搜索到的
资料起草候选知识库词条，存成候选文件供人工审核——不直接写库。

跟这个项目里其他"先生成候选、再人工审核"的脚本是同一个模式
（generate_eval_testset.py、之前的 router 评测集）：LLM 只负责起草，
真正决定"这条值不值得收进知识库"的是人，不是模型自己。

用法：
    cd backend
    python generate_kb_candidates.py

跑完之后：打开 app/knowledge/kb_candidates.json，把想采纳的条目的
"approved" 改成 true，再跑 approve_kb_candidates.py 才会真正写库。
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
from app.agent.rag import web_search
from app.services.kb_candidate_service import (
    build_kb_draft_prompt,
    fetch_uncovered_queries,
    group_uncovered_queries,
    parse_kb_draft_response,
)

OUT_FILE = Path("app/knowledge/kb_candidates.json")


async def main():
    await _db.init_pool()
    try:
        rows = await fetch_uncovered_queries(_db._pool)
        print(f"lookup_logs 里 source=web 的记录共 {len(rows)} 条")

        groups = group_uncovered_queries(rows, min_count=1)
        print(f"聚合后 {len(groups)} 个候选问题\n")

        if not groups:
            print("没有候选，不用生成任何东西。")
            return

        llm = get_llm()
        candidates = []
        for i, g in enumerate(groups, 1):
            query = g["query_text"]
            print(f"  [{i}/{len(groups)}] 起草：{query}（出现 {g['count']} 次）")
            try:
                material = await web_search(query)
                prompt = build_kb_draft_prompt(query, material)
                response = await llm.ainvoke(prompt)
                draft = parse_kb_draft_response(response.content)
            except Exception as e:
                print(f"      失败，跳过：{e}")
                continue

            if draft is None:
                print("      解析失败，跳过")
                continue

            candidates.append({
                "query_text": query,
                "count": g["count"],
                "topic": "auto_mined",
                "title": draft["title"],
                "content": draft["content"],
                "source": "网络搜索整理（待人工审核）",
                "approved": False,
                "inserted_at": None,
            })

        OUT_FILE.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n候选词条已保存到 {OUT_FILE.resolve()}，共 {len(candidates)} 条")
        print("下一步：打开这个文件人工审核，把想采纳的条目的 approved 改成 true，")
        print("改完再跑 python approve_kb_candidates.py 才会真正写进知识库。")
    finally:
        await _db.close_pool()


asyncio.run(main())
