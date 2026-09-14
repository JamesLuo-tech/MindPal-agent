"""把人工标记 approved=true 的候选词条写进 knowledge_base——但 approved 只是
"人工认可"，不能绕过自动检查：写入前会用当前最新的知识库内容重新跑一遍
自动检查（来源可信度/完整性/查重/可追溯性/时效性），只有全部通过才真正
落库，没通过的留在候选区，正式知识库继续用原有内容，不会因为人已经点了
"批准"就被动收录一条没通过校验的内容。

旧格式的候选（在这套自动检查上线前挖到的，没有 segments 字段，没法验证
来源合规性）会被明确跳过并打印提示，不会被当成"检查通过"处理——默认排除，
而不是默认收录。

已经写过的（inserted_at 不为空）不会重复插入，这个脚本可以放心反复跑。

用法：
    cd backend
    python approve_kb_candidates.py
"""
import asyncio
import io
import json
import sys

if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8")

from datetime import datetime, timezone
from pathlib import Path

import app.database as _db
from app.services.kb_candidate_service import (
    fetch_kb_contents,
    insert_approved_candidate,
    run_automated_checks,
)

CANDIDATES_FILE = Path("app/knowledge/kb_candidates.json")


async def main():
    if not CANDIDATES_FILE.exists():
        print(f"{CANDIDATES_FILE} 不存在，先跑 generate_kb_candidates.py 生成候选。")
        return

    candidates = json.loads(CANDIDATES_FILE.read_text(encoding="utf-8"))
    to_process = [c for c in candidates if c.get("approved") and not c.get("inserted_at")]

    if not to_process:
        print("没有待处理的已审核候选（要么还没人工审核，要么已经都写过了）。")
        return

    print(f"共 {len(to_process)} 条已标记 approved、待处理的候选")
    await _db.init_pool()
    inserted = 0
    held_back = 0
    try:
        kb_texts = await fetch_kb_contents(_db._pool)

        for c in to_process:
            if "segments" not in c:
                print(f"  [跳过] {c.get('title', c.get('query_text'))} —— 旧格式候选，没有来源片段数据，"
                      f"无法自动校验来源合规性，需要人工单独处理，不会自动写入")
                held_back += 1
                continue

            checks = run_automated_checks(c, kb_texts)
            c["checks"] = checks  # 写回最新的检查结果，即便这次没通过也留痕

            if not checks["all_passed"]:
                failed = [name for name, r in checks.items() if name != "all_passed" and not r["passed"]]
                print(f"  [暂不入库] {c['title']} —— 未通过自动检查：{', '.join(failed)}")
                for name in failed:
                    print(f"      {name}: {checks[name]['detail']}")
                held_back += 1
                continue

            source_url = c["segments"][0]["source_url"] if c["segments"] else None
            kb_id = await insert_approved_candidate(
                _db._pool, c["topic"], c["title"], c["content"], c["source"], source_url,
            )
            c["inserted_at"] = datetime.now(timezone.utc).isoformat()
            c["kb_id"] = kb_id
            kb_texts.append(c["content"])  # 同一批次内后面的查重要看到这条，避免批内重复都被放行
            print(f"  [已写入] {c['title']} -> {kb_id}")
            inserted += 1
    finally:
        await _db.close_pool()

    CANDIDATES_FILE.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完成：写入 {inserted} 条，因未通过自动检查/旧格式暂不入库 {held_back} 条")
    print(f"已更新 {CANDIDATES_FILE.resolve()}")


asyncio.run(main())
