"""数据库连接与初始化。"""
from pathlib import Path
import psycopg
from pgvector.psycopg import register_vector

from . import config

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def connect() -> psycopg.Connection:
    conn = psycopg.connect(config.require_db(), autocommit=True)
    register_vector(conn)
    return conn


def connect_catalog() -> psycopg.Connection:
    """连接纯 PostgreSQL 事实层，不要求 pgvector 扩展已安装。"""
    return psycopg.connect(config.require_db(), autocommit=True)


def init_catalog_schema() -> None:
    """只初始化第一阶段结构化目录表。"""
    schema = (SQL_DIR / "001_catalog_schema.sql").read_text(encoding="utf-8")
    with connect_catalog() as conn:
        conn.execute(schema)


def init_rag_schema() -> None:
    """初始化从 catalog 派生的 RAG 文档与向量表。"""
    schema = (SQL_DIR / "002_rag_schema.sql").read_text(encoding="utf-8")
    with psycopg.connect(config.require_db(), autocommit=True) as conn:
        conn.execute(schema)
