"""
RAG 离线评估脚本 —— 不依赖数据库，直接从 seed_data/ 读取知识库内容。

用法：
    cd backend
    python eval_rag.py
"""
import asyncio
import json
import re
from pathlib import Path

import numpy as np
import yaml
from datasets import Dataset
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_openai import ChatOpenAI
from ragas import evaluate
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import answer_relevancy, context_precision, faithfulness
from sentence_transformers import SentenceTransformer

from app.config import get_settings

SEED_DIR = Path("app/knowledge/seed_data")
EVAL_FILE = Path("app/knowledge/eval_questions.json")
TOP_K = 3

settings = get_settings()

eval_llm = ChatOpenAI(
    model="deepseek-chat",
    openai_api_key=settings.deepseek_api_key,
    openai_api_base=settings.deepseek_base_url,
    temperature=0,
)

# ── 读取知识库 ──────────────────────────────────────────────────────────────

def load_seed_data() -> list[dict]:
    docs = []
    for filepath in SEED_DIR.glob("*.md"):
        text = filepath.read_text(encoding="utf-8")
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
        if not match:
            continue
        meta = yaml.safe_load(match.group(1))
        body = text[match.end():].strip()
        docs.append({"title": meta.get("title", filepath.stem), "content": body})
    return docs


# ── 本地向量检索（替代 pgvector）──────────────────────────────────────────

_embedder: SentenceTransformer | None = None


def get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        print("加载 BGE-M3 模型...")
        _embedder = SentenceTransformer("BAAI/bge-m3")
    return _embedder


def local_search(query: str, docs: list[dict], top_k: int = TOP_K) -> list[str]:
    embedder = get_embedder()
    corpus = [d["title"] + " " + d["content"][:200] for d in docs]
    corpus_vecs = embedder.encode(corpus, normalize_embeddings=True)
    query_vec = embedder.encode(query, normalize_embeddings=True)
    scores = np.dot(corpus_vecs, query_vec)
    top_indices = np.argsort(scores)[::-1][:top_k]
    return [docs[i]["content"] for i in top_indices]


# ── 构建评估数据集 ─────────────────────────────────────────────────────────

async def build_dataset(docs: list[dict]) -> Dataset:
    with open(EVAL_FILE, encoding="utf-8") as f:
        questions = json.load(f)

    rows = []
    for item in questions:
        q = item["question"]
        contexts = local_search(q, docs)

        prompt = f"根据以下资料回答问题（用朋友聊天的语气，简洁）：\n{'---'.join(contexts)}\n\n问题：{q}"
        response = await eval_llm.ainvoke(prompt)
        answer = response.content

        rows.append({
            "question": q,
            "answer": answer,
            "contexts": contexts,
            "ground_truth": item.get("ground_truth", ""),
        })
        print(f"  [{len(rows)}/{len(questions)}] {q[:25]}...")

    return Dataset.from_list(rows)


# ── 主流程 ─────────────────────────────────────────────────────────────────

async def main():
    print("读取知识库...")
    docs = load_seed_data()
    print(f"共加载 {len(docs)} 篇文档\n")

    print("构建评估数据集（调用 DeepSeek 生成回答）...")
    dataset = await build_dataset(docs)
    print(f"\n数据集构建完成，共 {len(dataset)} 条\n")

    print("开始 RAGAS 评估...")
    ragas_llm = LangchainLLMWrapper(eval_llm)
    ragas_embeddings = LangchainEmbeddingsWrapper(
        HuggingFaceEmbeddings(model_name="BAAI/bge-m3")
    )
    result = evaluate(
        dataset,
        metrics=[faithfulness, answer_relevancy, context_precision],
        llm=ragas_llm,
        embeddings=ragas_embeddings,
    )

    print("\n── 评估结果 ──────────────────────────────")
    print(result)
    print("\n分数说明：")
    print("  faithfulness     > 0.8 → 回答忠实于检索内容，无幻觉")
    print("  answer_relevancy > 0.7 → 回答切题")
    print("  context_precision> 0.7 → 检索质量好，没捞回无关内容")

    out = Path("rag_eval_result.csv")
    result.to_pandas().to_csv(out, index=False)
    print(f"\n详细结果已保存到 {out.resolve()}")


asyncio.run(main())
