"""文献流水线编排：多源检索 → 去重入库 → 项目关联 → 分块/抽取（PDF 下载解析可选）。

用法：
    from autoresearch.literature import run_pipeline
    summary = run_pipeline(db, settings, project=project_row, query="RAG", sources=["arxiv"])
"""
from __future__ import annotations

import time
from pathlib import Path

from loguru import logger

from ..config import Settings, get_settings
from ..db import Database
from ..models import Paper
from .extractor import build_chunks, chunk_text
from .pdf_parser import download_pdf, parse_pdf
from .search import dedupe_key, search_all

__all__ = ["run_pipeline", "store_paper", "link_project_paper", "search_all", "dedupe_key"]

_PAPER_COLS = "(title, authors, year, venue, abstract, url, dedupe_key, metadata)"


def store_paper(db: Database, paper: Paper) -> tuple[int, bool]:
    """按 dedupe_key 去重入库。返回 (paper_id, 是否新建)。"""
    key = paper.dedupe_key or dedupe_key(paper.title, paper.year)
    pid = db.insert_ignore(
        f"INTO papers {_PAPER_COLS} VALUES ({db.ph}, {db.ph}, {db.ph}, {db.ph}, {db.ph}, {db.ph}, {db.ph}, {db.ph})",
        [paper.title, db.dumps(paper.authors), paper.year, paper.venue, paper.abstract,
         paper.url, key, db.dumps(paper.metadata or {})],
        conflict_cols="dedupe_key",
    )
    if pid is None:  # 已存在 → 取现有 id
        row = db.query_one(f"SELECT id FROM papers WHERE dedupe_key = {db.ph}", [key])
        return (row["id"] if row else 0), False
    return pid, True


def link_project_paper(db: Database, project_id: int, paper_id: int, query: str | None) -> bool:
    """建立项目—论文关联（幂等）。返回是否新建。"""
    row_id = db.insert_ignore(
        f"INTO projects_papers (project_id, paper_id, query) VALUES ({db.ph}, {db.ph}, {db.ph})",
        [project_id, paper_id, query],
        conflict_cols="project_id, paper_id",
    )
    return row_id is not None


def run_pipeline(db: Database, settings: Settings | None = None, *, project: dict,
                 query: str | None = None, sources: list[str] | tuple[str, ...] = ("arxiv",),
                 max_results: int = 50, download_pdfs: bool = False, pdf_limit: int = 10,
                 use_llm: bool = True, client=None) -> dict:
    """执行完整文献流水线，返回可序列化的执行摘要。"""
    settings = settings or get_settings()
    started = time.perf_counter()
    query = (query or project.get("question") or "").strip()

    papers, errors = search_all(query, settings, sources=list(sources),
                                max_results=max_results, client=client)

    new_papers = 0
    chunks_created = 0
    downloaded = parsed_ok = parsed_fail = 0
    pdf_dir = Path(settings.data_dir) / "papers"

    for paper in papers:
        paper_id, is_new = store_paper(db, paper)
        if not paper_id:
            continue
        new_papers += int(is_new)
        link_project_paper(db, project["id"], paper_id, query)

        texts = [paper.abstract] if paper.abstract else []
        pdf_url = (paper.metadata or {}).get("pdf_url")
        if download_pdfs and pdf_url and downloaded < pdf_limit:
            downloaded += 1
            dest = pdf_dir / f"{paper_id}.pdf"
            try:
                if not dest.exists():
                    download_pdf(pdf_url, dest, settings)
                parsed = parse_pdf(dest)
                texts = chunk_text(parsed["text"], settings.chunk_size, settings.chunk_overlap)
                parsed_ok += 1
                db.execute(f"UPDATE papers SET pdf_path = {db.ph} WHERE id = {db.ph}",
                           [str(dest), paper_id])
            except Exception as exc:
                parsed_fail += 1
                logger.warning("PDF 处理失败 paper#{} ({}): {}", paper_id, pdf_url, exc)
        if texts:
            chunks_created += build_chunks(db, settings, paper_id, texts, use_llm=use_llm)

    by_source: dict[str, int] = {}
    for p in papers:
        src = (p.metadata or {}).get("source", "unknown")
        by_source[src] = by_source.get(src, 0) + 1
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info("文献流水线完成 project#{}: {} 篇 / {} 新 / {} chunks / {:.1f}s",
                project["id"], len(papers), new_papers, chunks_created, elapsed_ms / 1000)
    return {
        "project_id": project["id"],
        "query": query,
        "papers_found": len(papers),
        "papers_new": new_papers,
        "chunks_created": chunks_created,
        "pdf_downloaded": downloaded,
        "pdf_parsed": parsed_ok,
        "pdf_failed": parsed_fail,
        "by_source": by_source,
        "errors": errors,
        "elapsed_ms": elapsed_ms,
    }
