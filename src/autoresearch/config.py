"""全局配置：pydantic-settings，环境变量前缀 AUTORESEARCH_，支持 .env 文件。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_LOCAL_LLM = "http://localhost:11434/v1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AUTORESEARCH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 基础
    app_name: str = "AutoResearch"
    version: str = "0.2.0"
    data_dir: Path = Path("data")

    # 数据库：空 = SQLite 零依赖模式；否则为 PostgreSQL DSN
    database_url: str = ""
    sqlite_path: Path = Path("data/autoresearch.db")
    migrations_dir: str = ""  # 覆盖默认迁移目录（默认按包定位）

    # LLM（OpenAI-compatible，本地优先）
    llm_base_url: str = DEFAULT_LOCAL_LLM
    llm_api_key: str = "ollama"
    llm_model: str = "qwen2.5:7b"
    llm_timeout: float = 120.0
    llm_max_concurrency: int = 4
    llm_temperature: float = 0.3
    llm_enabled: bool = True
    prompt_version: str = "v0"
    llm_cache_dir: Path = Path("data/cache/llm")

    # 嵌入 / 重排（可独立配置端点与模型）
    embed_base_url: str = DEFAULT_LOCAL_LLM
    embed_api_key: str = "ollama"
    embed_model: str = "BAAI/bge-m3"
    rerank_base_url: str = DEFAULT_LOCAL_LLM
    rerank_api_key: str = "ollama"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"

    # 服务
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    ui_port: int = 8501
    api_key: str = ""  # 非空时保护业务 API；空值保持本地开发免鉴权
    api_key_project_id: int | None = None  # 非空时把该 key 限定到单个项目
    rate_limit_per_minute: int = 120  # 进程内 IP/API Key 请求上限
    job_default_priority: int = 0
    job_max_priority: int = 100
    job_stale_after_seconds: int = 300
    job_max_attempts: int = 3
    job_retry_backoff_seconds: float = 0.2

    # 实验（阶段 4/5）：离线代理实验的数据集与执行参数
    experiment_datasets: str = "iris,wine,breast_cancer"
    experiment_folds: int = 5
    experiment_seeds: str = "0,1,2"
    experiment_timeout: float = 900.0
    sandbox_enabled: bool = True  # 是否尝试 Docker 沙箱
    execution_mode: str = "strict"  # strict / safe-local / unsafe-local
    allow_network: bool = False  # Docker 实验默认无网络
    max_output_bytes: int = 200_000
    job_max_workers: int = 2
    sandbox_cpus: float = 1.0
    sandbox_memory: str = "1g"
    sandbox_image: str = "python:3.12-slim"

    # 文献 API
    literature_max_results: int = 50
    http_timeout: float = 30.0
    chunk_size: int = 1200
    chunk_overlap: int = 150
    grobid_url: str = ""  # 可选 GROBID 服务地址；空 = 仅 pymupdf
    arxiv_api: str = "http://export.arxiv.org/api/query"
    semantic_scholar_api: str = "https://api.semanticscholar.org/graph/v1"
    semantic_scholar_key: str = ""
    pubmed_api: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    @field_validator("api_key_project_id", mode="before")
    @classmethod
    def empty_project_scope_is_unset(cls, value):
        return None if value == "" else value

    def ensure_dirs(self) -> None:
        """创建数据目录骨架（论文 PDF / 缓存 / 产物 / 实验工作区）。"""
        for sub in ("papers", "cache", "artifacts", "experiments"):
            (self.data_dir / sub).mkdir(parents=True, exist_ok=True)
        self.llm_cache_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def save_env_values(updates: dict[str, str], env_path: Path | None = None) -> Path:
    """把键值对写入 .env（保留文件中的其他行与注释；不存在则创建）。"""
    path = env_path or Path(".env")
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    for key, value in updates.items():
        clean = str(value).replace("\n", " ").strip()
        found = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
                lines[i] = f"{key}={clean}"
                found = True
                break
        if not found:
            lines.append(f"{key}={clean}")
    if lines and not lines[0].strip().startswith("#"):
        lines.insert(0, "# AutoResearch 本地配置（看板「设置」页生成/更新；勿提交到 git）")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def reload_settings() -> Settings:
    """清空缓存并重新加载配置（看板保存设置后调用，立即生效）。"""
    get_settings.cache_clear()
    return get_settings()
