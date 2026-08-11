"""远程或本地的 embedding 封装。"""
from __future__ import annotations
import json
from functools import lru_cache
from urllib.request import Request, urlopen

from pgvector import SparseVector, Vector

from . import config

_MODEL_NAME = "BAAI/bge-m3"


@lru_cache(maxsize=1)
def _model():
    # 延迟加载, 避免非 embedding 命令也吃启动开销
    from FlagEmbedding import BGEM3FlagModel
    return BGEM3FlagModel(_MODEL_NAME, use_fp16=True)


def prepare() -> None:
    """仅在显式本地模式预加载 BGE-M3。"""
    if config.embedding_mode() == "local":
        _model()


def description() -> str:
    if config.embedding_mode() == "local":
        return "加载本地 BGE-M3 模型（首次执行会下载模型文件）..."
    return f"使用远程 Embedding 模型: {config.require_embedding_model()}"


def _embed_remote(texts: list[str]) -> list[dict]:
    body = json.dumps(
        {"model": config.require_embedding_model(), "input": texts},
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(
        config.embedding_url(),
        data=body,
        headers={
            "Authorization": f"Bearer {config.require_embedding_api_key()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=120) as response:
        payload = json.loads(response.read().decode("utf-8"))

    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) != len(texts):
        raise RuntimeError("Embedding 服务返回的数据数量与输入不一致")
    rows.sort(key=lambda row: row.get("index", 0))
    result = []
    for row in rows:
        dense = row.get("embedding") if isinstance(row, dict) else None
        if not isinstance(dense, list) or not dense:
            raise RuntimeError("Embedding 服务未返回浮点向量")
        result.append({"dense": Vector(dense), "sparse": None})
    return result


def embed(texts: list[str]) -> list[dict]:
    """返回每条文本的 dense 向量；本地模式额外返回 sparse 向量。"""
    if config.embedding_mode() == "remote":
        return _embed_remote(texts)

    out = _model().encode(
        texts,
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,
    )
    results = []
    for dense, lex in zip(out["dense_vecs"], out["lexical_weights"]):
        sparse_map = {int(tid): float(w) for tid, w in lex.items()}
        results.append({
            "dense": Vector(dense.tolist()),
            "sparse": SparseVector(sparse_map, config.SPARSE_DIM),
        })
    return results


def embed_one(text: str) -> dict:
    return embed([text])[0]
