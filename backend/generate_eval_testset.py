"""
半自动生成 RAG 评测候选问题集 —— 用 ragas.testset.TestsetGenerator 从
app/knowledge/seed_data/ 的 24 篇文档里批量出题，取代手写。

跟手写的关键区别：
  - 会自动生成两类问题：single-hop（单篇文档就能回答，测 context_precision）
    和 multi-hop（需要综合多篇文档的信息才能回答，测 context_recall），
    覆盖到目前手写题目集完全没测过的"跨文档综合"能力
  - 24 篇文档全部喂进去建知识图谱，天然不会像手写那样漏掉一半的文档

产出的是"候选集"，不直接覆盖 eval_questions.json —— synthesizer 生成的
ground_truth 有时会跑题或者引用了不该引用的上下文，必须人工过一遍筛选/
修改后再合并，这一步不能省。

用法：
    cd backend
    python generate_eval_testset.py
"""
import re
from pathlib import Path

from langchain_core.documents import Document
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_openai import ChatOpenAI
from ragas.run_config import RunConfig
from ragas.testset import TestsetGenerator
from ragas.testset.graph import KnowledgeGraph, Node, NodeType
from ragas.testset.transforms import (
    CosineSimilarityBuilder,
    CustomNodeFilter,
    EmbeddingExtractor,
    OverlapScoreBuilder,
    Parallel,
    SummaryExtractor,
    apply_transforms,
)
from ragas.testset.transforms.default import NERExtractor, ThemesExtractor
from ragas.testset.persona import Persona
import yaml

from app.config import get_settings

LLM_CONTEXT_ZH = (
    "这是一个面向中文用户的心理健康陪伴产品，知识库和真实用户提问全部是简体中文口语化表达。"
    "生成的问题、人物设定描述、参考答案都必须使用简体中文，不要出现英文单词或英文整句。"
)

# 不给自定义 persona_list 的话，模型会自己编人物设定，语言风格会飘到英文——
# 这三个 persona 对应真实用户群体：直接倾诉自己情况的、想帮身边人的、想系统了解某个概念的，
# 跟这份知识库本身覆盖的场景对应。
ZH_PERSONAS = [
    Persona(
        name="正在经历情绪困扰的用户",
        role_description="用口语化的中文第一人称描述自己正在经历的具体情绪或身体感受（比如失眠、焦虑发作、提不起劲），倾向于直接倾诉而不是查百科式提问",
    ),
    Persona(
        name="想帮助身边人的用户",
        role_description="身边的朋友或家人正在经历心理困扰，用中文口语化提问自己具体能做什么、不该说什么，关心的是实际可执行的建议",
    ),
    Persona(
        name="想系统了解某个概念的用户",
        role_description="想弄清楚 CBT、正念、SSRI 等心理健康相关的具体概念或方法，提问偏书面咨询语气但仍然是简体中文",
    ),
]

SEED_DIR = Path("app/knowledge/seed_data")
OUT_FILE = Path("app/knowledge/eval_questions_candidates.json")
KG_CACHE_FILE = Path("eval_knowledge_graph.json")
TESTSET_SIZE = 30  # 24 篇文档，目标是每篇至少覆盖到，外加一批跨文档综合题

# DeepSeek 在默认 max_workers=16 的并发下偶尔会报 APIConnectionError（重试 10 次后仍失败，
# 大概率是账号并发上限），把知识图谱构建和出题两阶段的并发都调低一些更稳。
LOW_CONCURRENCY_CONFIG = RunConfig(max_workers=4, timeout=120, max_retries=6, max_wait=30)

settings = get_settings()


def load_seed_docs() -> list[Document]:
    """跟 eval_rag.py 的 load_seed_data 读同一批文件，包成 LangChain Document。"""
    docs = []
    for filepath in sorted(SEED_DIR.glob("*.md")):
        text = filepath.read_text(encoding="utf-8")
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
        if not match:
            continue
        meta = yaml.safe_load(match.group(1))
        body = text[match.end():].strip()
        title = meta.get("title", filepath.stem)
        docs.append(Document(
            page_content=f"{title}\n\n{body}",
            metadata={"title": title, "filename": filepath.stem},
        ))
    return docs


def build_short_doc_transforms(llm, embedder):
    """ragas 的 default_transforms 会按语料里长文档的占比自动选流水线：
    如果 >=25% 的文档超过 500 token，就整体切到"长文档"分支——用
    HeadlinesExtractor 抽标题、HeadlineSplitter 按标题切分。
    我们这 24 篇种子文档大多是 20-30 行的短文，没有 markdown 二级标题，
    混进去的几篇稍长的文档就把整个语料判成了"长文档"模式，导致其余
    没有标题结构的短文档在切分那一步直接报错（'headlines' property not found）。

    这里手动搭一条对标 ragas 短文档分支的流水线，把每篇种子文档当成一个
    原子节点（本来就是单主题的短文，没必要再切），跳过标题抽取/切分这一步。
    """
    def filter_docs(node):
        return node.type == NodeType.DOCUMENT

    summary_extractor = SummaryExtractor(llm=llm, filter_nodes=filter_docs)
    summary_emb_extractor = EmbeddingExtractor(
        embedding_model=embedder,
        property_name="summary_embedding",
        embed_property_name="summary",
        filter_nodes=filter_docs,
    )
    cosine_sim_builder = CosineSimilarityBuilder(
        property_name="summary_embedding",
        new_property_name="summary_similarity",
        threshold=0.5,
        filter_nodes=filter_docs,
    )
    ner_extractor = NERExtractor(llm=llm, filter_nodes=filter_docs)
    ner_overlap_sim = OverlapScoreBuilder(threshold=0.01, filter_nodes=filter_docs)
    theme_extractor = ThemesExtractor(llm=llm, filter_nodes=filter_docs)
    node_filter = CustomNodeFilter(llm=llm, filter_nodes=filter_docs)

    return [
        summary_extractor,
        node_filter,
        Parallel(summary_emb_extractor, theme_extractor, ner_extractor),
        Parallel(cosine_sim_builder, ner_overlap_sim),
    ]


def guess_topics(reference_contexts: list[str], docs: list[Document]) -> list[str]:
    """从生成样本引用的原文片段里，反查最像是出自哪几篇文档——纯粹方便人工审核时
    按主题分组看，不要求精确，猜错了人工审核那一步会看出来。

    multi-hop 样本会引用好几段，各自带 "<1-hop>"/"<2-hop>" 这样的前缀标记，
    要先把前缀去掉再去匹配文档正文，而且要把每一段引用到的文档都列出来，
    不能只看第一段——不然 multi-hop 那一类几乎全部显示成 unknown。
    """
    topics = []
    for ctx in reference_contexts:
        cleaned = re.sub(r"^<\d+-hop>\s*", "", ctx).strip()
        snippet = cleaned[:30]
        for doc in docs:
            if snippet and snippet in doc.page_content:
                topics.append(doc.metadata["filename"])
                break
    return topics or ["unknown"]


def build_or_load_knowledge_graph(docs: list[Document], generator: TestsetGenerator) -> KnowledgeGraph:
    """知识图谱构建这一步本身不便宜（每篇文档都要过好几个 LLM extractor），
    成功一次就存盘缓存——万一后面出题那一步再因为网络问题失败，重跑脚本
    不用重新烧一遍知识图谱构建的 token 和时间，直接读缓存接着跑出题。
    """
    if KG_CACHE_FILE.exists():
        print(f"发现已缓存的知识图谱（{KG_CACHE_FILE}），跳过重新构建...")
        return KnowledgeGraph.load(str(KG_CACHE_FILE))

    print("构建知识图谱（摘要、关键词、实体、跨文档关联）...")
    nodes = [
        Node(
            type=NodeType.DOCUMENT,
            properties={"page_content": doc.page_content, "document_metadata": doc.metadata},
        )
        for doc in docs
    ]
    kg = KnowledgeGraph(nodes=nodes)
    # 自定义 transforms 里的每个 extractor/builder 要吃 ragas 包过的 BaseRagasLLM/
    # BaseRagasEmbeddings（有 embed_text 这类异步接口），不是原始的 LangChain 对象——
    # from_langchain() 内部已经包过一次，直接复用 generator 上已包好的这两个。
    transforms = build_short_doc_transforms(generator.llm, generator.embedding_model)
    apply_transforms(kg, transforms, run_config=LOW_CONCURRENCY_CONFIG)

    kg.save(str(KG_CACHE_FILE))
    print(f"知识图谱构建完成，已缓存到 {KG_CACHE_FILE}\n")
    return kg


def main():
    print("读取知识库文档...")
    docs = load_seed_docs()
    print(f"共 {len(docs)} 篇\n")

    llm = ChatOpenAI(
        model="deepseek-chat",
        openai_api_key=settings.deepseek_api_key,
        openai_api_base=settings.deepseek_base_url,
        temperature=0,
    )
    embedder = HuggingFaceEmbeddings(model_name="BAAI/bge-m3")

    generator = TestsetGenerator.from_langchain(
        llm=llm, embedding_model=embedder, llm_context=LLM_CONTEXT_ZH,
    )
    generator.persona_list = ZH_PERSONAS
    generator.knowledge_graph = build_or_load_knowledge_graph(docs, generator)

    print(f"生成候选测试集（目标 {TESTSET_SIZE} 条，包含 single-hop 和 multi-hop 两类）...")
    testset = generator.generate(
        testset_size=TESTSET_SIZE,
        num_personas=len(ZH_PERSONAS),
        run_config=LOW_CONCURRENCY_CONFIG,
        with_debugging_logs=True,
    )

    rows = []
    for sample in testset.samples:
        s = sample.eval_sample
        rows.append({
            "question": s.user_input,
            "ground_truth": s.reference,
            "synthesizer": sample.synthesizer_name,
            "topic_guess": guess_topics(s.reference_contexts or [], docs),
            "reference_contexts": s.reference_contexts,
        })

    import json
    OUT_FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    from collections import Counter
    dist = Counter(r["synthesizer"] for r in rows)
    print(f"\n生成完成，共 {len(rows)} 条候选，已写入 {OUT_FILE.resolve()}")
    print("题型分布：")
    for name, count in dist.items():
        print(f"  {name}: {count}")
    print("\n下一步：人工过一遍，删掉跑题/答案质量差的，保留的合并进 eval_questions.json。")


if __name__ == "__main__":
    main()
