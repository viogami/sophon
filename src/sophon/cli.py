"""CLI: 结构化数据入库与后续 RAG 工具。"""
from __future__ import annotations
import time
from pathlib import Path
from typing import Optional

import typer

app = typer.Typer(add_completion=False, help="动漫角色结构化数据目录与后续 RAG 工具")


@app.command("init-catalog-db")
def init_catalog_db():
    """只建第一阶段结构化目录表，不依赖 pgvector。"""
    from . import db
    db.init_catalog_schema()
    print("catalog schema 初始化完成")


@app.command("init-rag-db")
def init_rag_db():
    """建立从 catalog 派生角色文档所需的 pgvector 表。"""
    from . import db
    db.init_rag_schema()
    print("RAG schema 初始化完成")


@app.command("ingest-moegirl")
def ingest_moegirl(
    data_dir: Optional[Path] = typer.Option(
        None,
        "--data-dir",
        help="萌娘 JSON 目录，默认 data/moegirl",
    ),
    bangumi_dir: Optional[Path] = typer.Option(
        None,
        "--bangumi-dir",
        help="Bangumi 映射目录，默认 data/bangumi",
    ),
    limit: Optional[int] = typer.Option(
        None,
        "--limit",
        min=1,
        help="限制导入角色数，适合先小批量验证",
    ),
    offset: int = typer.Option(0, "--offset", min=0),
    changed_only: bool = typer.Option(
        False,
        "--changed-only",
        help="仅写入新增或原始载荷发生变化的角色；必须不带 --reset 使用。",
    ),
    reset: bool = typer.Option(
        False,
        "--reset/--no-reset",
        help="清空第一阶段目录表后完整重建；不会删除 RAG docs 表。",
    ),
):
    """把 data/moegirl 写入可追溯的结构化目录表。"""
    if reset and changed_only:
        raise typer.BadParameter("--changed-only 不能与 --reset 同时使用")
    from .importers import moegirl
    from .loaders import moegirl as loader

    print("读取并解析萌娘 DB JSON...", flush=True)
    started_at = time.monotonic()
    dataset = moegirl.build_dataset(
        moegirl_dir=data_dir,
        bangumi_dir=bangumi_dir,
        limit=limit,
        offset=offset,
    )
    elapsed = time.monotonic() - started_at
    print(
        f"解析完成: {len(dataset.characters):,} 个角色、"
        f"{len(dataset.source_artifacts)} 个原始文件 ({elapsed:.1f}s)",
        flush=True,
    )
    loader.load(dataset, reset=reset, changed_only=changed_only)


@app.command("build-rag")
def build_rag(
    batch_size: int = typer.Option(32, "--batch-size", min=1),
    reset: bool = typer.Option(True, "--reset/--no-reset"),
):
    """从 catalog 的有效角色生成 RAG 文档和 bge-m3 向量。"""
    from . import rag_projection
    rag_projection.rebuild(batch_size=batch_size, reset=reset)


@app.command()
def ask(query: str, top_k: int = 5, no_extract: bool = typer.Option(False, "--no-extract")):
    """提问并给出 grounded 回答。"""
    from . import pipeline
    result = pipeline.answer(query, top_k=top_k, use_extract=not no_extract)

    if not no_extract:
        print(f"[抽取特征] {result['features']}\n")
    print("[召回候选]")
    for c in result["candidates"]:
        print(f"  [doc:{c['id']}] {c.get('name')} ({c.get('work_title') or '未知作品'}) "
              f"rrf={c['rrf_score']}")
    print("\n[回答]\n" + result["answer"])


@app.command()
def retrieve(query: str, top_k: int = 5):
    """只看检索结果 (不调用生成), 用于调检索策略。"""
    from . import retrieve as _r
    print("编码查询并检索角色文档...", flush=True)
    for c in _r.retrieve(query, top_k=top_k):
        print(f"[doc:{c['id']}] {c.get('name')} ({c.get('work_title') or '未知作品'}) "
              f"rrf={c['rrf_score']}")


if __name__ == "__main__":
    app()
