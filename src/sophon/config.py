"""配置: 从环境变量 / .env 读取。"""
import os
import anthropic
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")
# LLM_* 为当前配置；旧变量保留为兼容回退，便于已有部署平滑迁移。
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("ANTHROPIC_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL") or os.getenv("ANTHROPIC_BASE_URL", "")
LLM_MODEL = os.getenv("LLM_MODEL") or os.getenv("CLAUDE_MODEL", "")
# 默认使用 OpenAI Embeddings 兼容的远程服务，并复用 CCSwitch 的认证信息。
# 只有显式设为 local 时才加载 BGE-M3。
EMBEDDING_MODE = os.getenv("EMBEDDING_MODE", "remote").strip().lower()
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY") or LLM_API_KEY
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL") or LLM_BASE_URL
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "")
SPARSE_DIM = 250002

_PLACEHOLDER_VALUES = {"", "sk-ant-...", "your-api-key", "your-ccswitch-key"}
_BASE_URL_PLACEHOLDERS = {"https://your-ccswitch-host/v1", "your-ccswitch-url"}


def require_db() -> str:
    if not DATABASE_URL:
        raise SystemExit("请在 .env 设置 DATABASE_URL")
    return DATABASE_URL


def _require_llm_value(value: str, name: str) -> str:
    if value.strip() in _PLACEHOLDER_VALUES:
        raise SystemExit(f"请在 .env 设置 {name}")
    return value.strip()


def require_llm_model() -> str:
    return _require_llm_value(LLM_MODEL, "LLM_MODEL")


def llm_client() -> anthropic.Anthropic:
    """创建 Anthropic 协议客户端；LLM_BASE_URL 可指向 CCSwitch 中转地址。"""
    options: dict[str, str] = {"api_key": _require_llm_value(LLM_API_KEY, "LLM_API_KEY")}
    base_url = LLM_BASE_URL.strip()
    if base_url:
        if base_url in _BASE_URL_PLACEHOLDERS:
            raise SystemExit("请在 .env 设置 LLM_BASE_URL")
        options["base_url"] = base_url.rstrip("/")
    return anthropic.Anthropic(**options)


def embedding_mode() -> str:
    if EMBEDDING_MODE not in {"remote", "local"}:
        raise SystemExit("EMBEDDING_MODE 只能是 remote 或 local")
    return EMBEDDING_MODE


def require_embedding_model() -> str:
    return _require_llm_value(EMBEDDING_MODEL, "EMBEDDING_MODEL")


def embedding_url() -> str:
    """返回 OpenAI Embeddings 兼容接口地址。"""
    base_url = EMBEDDING_BASE_URL.strip()
    if not base_url or base_url in _BASE_URL_PLACEHOLDERS:
        raise SystemExit("请在 .env 设置 EMBEDDING_BASE_URL 或 LLM_BASE_URL")
    return base_url.rstrip("/") + "/embeddings"


def require_embedding_api_key() -> str:
    return _require_llm_value(EMBEDDING_API_KEY, "EMBEDDING_API_KEY")
