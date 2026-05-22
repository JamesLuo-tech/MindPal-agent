"""批量将 seed_data/ 下的 Markdown 知识条目写入 knowledge_base 表。

用法（在 backend/ 目录下运行）：
    python -m app.knowledge.ingest
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

# Windows 终端默认 GBK，强制 UTF-8 输出避免打印中文/特殊字符报错
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import asyncpg
import numpy as np
import yaml
from pgvector.asyncpg import register_vector
from sentence_transformers import SentenceTransformer

SEED_DIR = Path(__file__).parent / "seed_data"

_embedder: SentenceTransformer | None = None


def get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        print("  加载 BGE-M3 模型（首次运行会下载约 2GB，请耐心等待）...")
        _embedder = SentenceTransformer("BAAI/bge-m3")
        print("  模型加载完成")
    return _embedder


def parse_markdown(filepath: Path) -> dict:
    """解析 Markdown 文件的 YAML front-matter 和正文。"""
    text = filepath.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        raise ValueError(f"{filepath.name}: 缺少 YAML front-matter（--- 块）")

    meta = yaml.safe_load(match.group(1))
    body = text[match.end():].strip()

    return {
        "topic": meta.get("topic", "general"),
        "title": meta.get("title", filepath.stem),
        "question_variants": meta.get("question_variants", []),
        "content": body,
        "source": meta.get("source", ""),
        "source_url": meta.get("source_url", ""),
        "quality_score": float(meta.get("quality_score", 1.0)),
    }


def compute_embedding(text: str) -> np.ndarray:
    """用 BGE-M3 计算归一化向量。"""
    return get_embedder().encode(text, normalize_embeddings=True)


async def ingest_file(conn: asyncpg.Connection, filepath: Path) -> bool:
    """入库单个文件。若已存在同标题条目则跳过，返回是否插入。"""
    data = parse_markdown(filepath)

    # 去重：同 title 已存在则跳过
    existing = await conn.fetchval(
        "SELECT id FROM knowledge_base WHERE title = $1", data["title"]
    )
    if existing:
        print(f"    已存在，跳过: {data['title']}")
        return False

    # 用 title + 前 200 字内容 拼接后编码，提升语义覆盖
    embed_text = data["title"] + " " + data["content"][:200]
    vec = compute_embedding(embed_text)

    await conn.execute(
        """
        INSERT INTO knowledge_base
            (topic, title, question_variants, content, source, source_url, embedding, quality_score)
        VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7, $8)
        """,
        data["topic"],
        data["title"],
        json.dumps(data["question_variants"], ensure_ascii=False),
        data["content"],
        data["source"],
        data["source_url"],
        vec,
        data["quality_score"],
    )
    print(f"    [OK] 入库: {data['title']} [{data['topic']}]")
    return True


async def main() -> None:
    from app.config import get_settings
    settings = get_settings()

    if not settings.database_url:
        print("错误: DATABASE_URL 未配置，请先填写 .env")
        sys.exit(1)

    files = sorted(SEED_DIR.glob("*.md"))
    if not files:
        print(f"seed_data/ 下没有找到 .md 文件: {SEED_DIR}")
        sys.exit(1)

    print(f"找到 {len(files)} 个知识文件，开始入库...\n")

    conn = await asyncpg.connect(settings.database_url)
    await register_vector(conn)

    inserted = 0
    skipped = 0
    errors = 0

    for filepath in files:
        print(f"  处理: {filepath.name}")
        try:
            ok = await ingest_file(conn, filepath)
            if ok:
                inserted += 1
            else:
                skipped += 1
        except Exception as e:
            print(f"    [ERR] 失败: {e}")
            errors += 1

    await conn.close()

    print(f"\n完成：新增 {inserted} 条，跳过 {skipped} 条，失败 {errors} 条")


if __name__ == "__main__":
    asyncio.run(main())
