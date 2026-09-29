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
