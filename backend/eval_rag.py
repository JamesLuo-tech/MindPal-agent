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
from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness
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


def _single_search(query: str, corpus_vecs: np.ndarray, top_k: int) -> list[int]:
    embedder = get_embedder()
    query_vec = embedder.encode(query, normalize_embeddings=True)
    scores = np.dot(corpus_vecs, query_vec)
    return np.argsort(scores)[::-1][:top_k].tolist()


async def generate_query_variants(query: str) -> list[str]:
    """用 LLM 将原始查询改写成多种表达，提高召回率。"""
    prompt = (
        "请将以下问题改写成3种不同的表达方式，用于检索心理健康知识库。\n"
        "每种改写单独一行，不要加编号或标点前缀。\n\n"
        f"原始问题：{query}\n\n3种改写："
    )
    response = await eval_llm.ainvoke(prompt)
    variants = [q.strip() for q in response.content.strip().split("\n") if q.strip()]
    return [query] + variants[:3]


def _rrf(rank_lists: list[list[int]], k: int = 60) -> list[int]:
    """Reciprocal Rank Fusion：对多组排名列表重新打分，返回合并后的排名。"""
    scores: dict[int, float] = {}
    for ranked in rank_lists:
        for rank, idx in enumerate(ranked):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda x: scores[x], reverse=True)


async def local_search(query: str, docs: list[dict], corpus_vecs: np.ndarray, top_k: int = TOP_K) -> list[str]:
    """RAG Fusion 本地检索：生成查询变体 → 各自检索 → RRF 重排。"""
    variants = await generate_query_variants(query)
    rank_lists = [_single_search(q, corpus_vecs, top_k) for q in variants]
    fused = _rrf(rank_lists)
    return [docs[i]["content"] for i in fused[:top_k]]


# ── 构建评估数据集 ─────────────────────────────────────────────────────────

async def build_dataset(docs: list[dict]) -> Dataset:
    with open(EVAL_FILE, encoding="utf-8") as f:
        questions = json.load(f)

    embedder = get_embedder()
    corpus = [d["title"] + " " + d["content"][:200] for d in docs]
    corpus_vecs = embedder.encode(corpus, normalize_embeddings=True)

    rows = []
    for item in questions:
        q = item["question"]
        contexts = await local_search(q, docs, corpus_vecs)

        prompt = f"根据以下资料回答问题（用朋友聊天的语气，简洁），只基于以下资料回答，不要补充资料外的内容：\n{'---'.join(contexts)}\n\n问题：{q}"
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
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
        llm=ragas_llm,
        embeddings=ragas_embeddings,
    )

    print("\n── 评估结果 ──────────────────────────────")
    print(result)
    print("\n分数说明：")
    print("  faithfulness     > 0.8 → 回答忠实于检索内容，无幻觉")
    print("  answer_relevancy > 0.7 → 回答切题")
    print("  context_precision> 0.7 → 检索质量好，没捞回无关内容")
    print("  context_recall   > 0.7 → ground_truth 中的知识点被检索内容覆盖")

    out = Path("rag_eval_result.csv")
    result.to_pandas().to_csv(out, index=False)
    print(f"\n详细结果已保存到 {out.resolve()}")


asyncio.run(main())
