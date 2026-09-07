"""把人工审核标记过 approved=true 的候选词条真正写进 knowledge_base。

已经写过的（inserted_at 不为空）不会重复插入，这个脚本可以放心反复跑——
每次只处理"审核过、但还没真正落库"的那一批。

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
from app.services.kb_candidate_service import insert_approved_candidate

CANDIDATES_FILE = Path("app/knowledge/kb_candidates.json")


async def main():
    if not CANDIDATES_FILE.exists():
        print(f"{CANDIDATES_FILE} 不存在，先跑 generate_kb_candidates.py 生成候选。")
        return

    candidates = json.loads(CANDIDATES_FILE.read_text(encoding="utf-8"))
    to_insert = [c for c in candidates if c.get("approved") and not c.get("inserted_at")]

    if not to_insert:
        print("没有待写入的已审核候选（要么还没人工审核，要么已经都写过了）。")
        return

    print(f"共 {len(to_insert)} 条已审核、待写入知识库的候选")
    await _db.init_pool()
    try:
        for c in to_insert:
            kb_id = await insert_approved_candidate(
                _db._pool, c["topic"], c["title"], c["content"], c["source"],
            )
            c["inserted_at"] = datetime.now(timezone.utc).isoformat()
            c["kb_id"] = kb_id
            print(f"  已写入: {c['title']} -> {kb_id}")
    finally:
        await _db.close_pool()

    CANDIDATES_FILE.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完成，已更新 {CANDIDATES_FILE.resolve()}")


asyncio.run(main())
