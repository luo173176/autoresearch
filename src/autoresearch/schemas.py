"""Pydantic 请求/响应模型（API 层）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class HealthOut(BaseModel):
    status: str
    app: str
    version: str
    backend: str
    database: bool
    time: datetime


class JobAccepted(BaseModel):
    job_id: int
    status: str
    type: str
    poll_url: str


class JobOut(BaseModel):
    id: int
    project_id: int | None = None
    type: str
    status: str
    progress: int
    priority: int = 0
    current_step: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = None
    error: str | None = None
    idempotency_key: str | None = None
    attempt_count: int = 0
    heartbeat_at: datetime | str | None = None
    worker_id: str | None = None
    created_at: datetime | str | None = None
    started_at: datetime | str | None = None
    finished_at: datetime | str | None = None


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1)
    domain: str = "general"
    budget: dict[str, Any] = Field(default_factory=dict)


class ProjectOut(BaseModel):
    # created_at：PostgreSQL 返回 datetime，SQLite 返回字符串，统一透出
    id: int
    name: str
    question: str
    domain: str
    budget: dict[str, Any]
    status: str
    created_at: datetime | str | None = None


# ---------- 文献（阶段 1） ----------
class LiteratureRequest(BaseModel):
    query: str | None = None  # 缺省使用项目研究问题
    sources: list[str] = Field(default_factory=lambda: ["arxiv"])
    max_results: int = Field(default=50, ge=1, le=200)
    download_pdfs: bool = False
    pdf_limit: int = Field(default=10, ge=0, le=50)
    use_llm: bool = True


class LiteratureSummary(BaseModel):
    project_id: int
    query: str
    papers_found: int
    papers_new: int
    chunks_created: int
    pdf_downloaded: int
    pdf_parsed: int
    pdf_failed: int
    by_source: dict[str, int]
    errors: dict[str, str]
    elapsed_ms: int


class PaperOut(BaseModel):
    id: int
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    abstract: str | None = None
    url: str | None = None
    pdf_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PaperImportRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    authors: list[str] = Field(default_factory=list)
    year: int | None = Field(default=None, ge=0, le=3000)
    venue: str | None = None
    abstract: str | None = None
    url: str | None = None
    text: str | None = Field(default=None, description="可选全文；提供后会自动分块")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchRequest(BaseModel):
    mode: str = Field(default="auto", pattern="^(auto|custom)$")
    framework: dict[str, str] = Field(default_factory=dict)
    query: str | None = Field(default=None, description="提供后先自动检索文献，再进行研究")
    sources: list[str] = Field(default_factory=lambda: ["arxiv"])
    max_results: int = Field(default=50, ge=1, le=200)
    download_pdfs: bool = False
    pdf_limit: int = Field(default=10, ge=0, le=50)
    paper_ids: list[int] | None = None
    use_llm: bool = True
    max_chunks: int = Field(default=80, ge=1, le=300)


class ResearchSummary(BaseModel):
    research_id: int
    project_id: int
    mode: str
    framework: dict[str, str]
    paper_ids: list[int]
    papers_used: int
    chunks_used: int
    result: dict[str, Any]
    llm_used: bool
    elapsed_ms: int


# ---------- 知识图谱（阶段 2） ----------
class GraphBuildRequest(BaseModel):
    use_llm: bool = True


class GraphBuildSummary(BaseModel):
    project_id: int
    chunks_processed: int
    entities_created: int
    relations_created: int
    contradictions: int
    findings: int
    by_type: dict[str, int]
    relations_total: int
    llm_used: bool
    elapsed_ms: int


# ---------- 假设生成（阶段 3） ----------
class HypothesisGenerateRequest(BaseModel):
    max_hypotheses: int = Field(default=50, ge=1, le=200)
    use_llm: bool = True


class HypothesisGenerateSummary(BaseModel):
    project_id: int
    candidates: int
    generated: int
    stored: int
    by_source: dict[str, int]
    llm_used: bool
    elapsed_ms: int


class HypothesisOut(BaseModel):
    id: int
    project_id: int
    statement: str
    rationale: str | None = None
    testability: dict[str, Any] = Field(default_factory=dict)
    novelty: float = 0.5
    status: str = "proposed"
    metadata: dict[str, Any] = Field(default_factory=dict)
