"""编排: query -> 抽取特征 -> 混合检索 -> 基于候选资料生成回答。"""
from __future__ import annotations
from . import extract, retrieve, generate


def answer(query: str, top_k: int = 5, use_extract: bool = True) -> dict:
    if use_extract:
        print("通过 LLM 提取检索特征...", flush=True)
        features = extract.extract(query)
    else:
        features = {}

    # keywords 并入检索 query, 增强向量检索对经历类线索的召回。
    kw = " ".join(features.get("keywords", []))
    search_query = f"{query} {kw}".strip()

    print("编码查询并检索角色文档...", flush=True)
    candidates = retrieve.retrieve(
        search_query, features=features, top_k=top_k
    )

    print("基于候选资料生成回答...", flush=True)
    reply = generate.generate(query, candidates)
    return {
        "query": query,
        "features": features,
        "candidates": candidates,
        "answer": reply,
    }
