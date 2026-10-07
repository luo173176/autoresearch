"""统一研究引擎：自动检索和用户导入的文献共用同一套框架分析。"""

from __future__ import annotations

import time
from typing import Any

from loguru import logger

from .config import Settings, get_settings
from .db import Database

DEFAULT_FRAMEWORK = {
    "research_question": "这组文献研究了什么问题？问题边界和核心概念是什么？",
    "methods": "使用了哪些数据、方法、实验设计或理论框架？",
    "findings": "主要发现和证据是什么？不同文献之间有哪些共识？",
    "limitations": "有哪些局限、偏差、未解决的问题或证据不足？",
    "gaps": "还缺少哪些研究，下一步最值得验证什么？",
}


def _deterministic_result(framework: dict[str, str], chunks: list[dict]) -> dict[str, Any]:
    """LLM 关闭时仍返回可用的、可追溯的研究草稿。"""
    by_section = {}
    excerpts = [
        {"chunk_id": c["id"], "paper_id": c["paper_id"], "excerpt": c["text"][:800]} for c in chunks
    ]
    for name, instruction in framework.items():
        relevant = [c.get("summary") or c["text"][:400] for c in chunks[:8]]
        by_section[name] = {
            "instruction": instruction,
            "draft": "；".join(relevant) if relevant else "暂无可用文本",
            "evidence_chunk_ids": [c["id"] for c in chunks[:8]],
        }
    return {
        "sections": by_section,
        "evidence": excerpts,
        "note": "LLM 未启用，以上为可追溯规则草稿。",
    }


def run_framework_research(
    db: Database,
    settings: Settings | None,
    *,
    project_id: int,
    mode: str = "auto",
    framework: dict[str, str] | None = None,
    paper_ids: list[int] | None = None,
    use_llm: bool = True,
    max_chunks: int = 80,
    query: str | None = None,
    sources: list[str] | None = None,
    max_results: int = 50,
    download_pdfs: bool = False,
    pdf_limit: int = 10,
) -> dict[str, Any]:
    settings = settings or get_settings()
    started = time.perf_counter()
    if query:
        from .literature import run_pipeline

        project = db.query_one(f"SELECT * FROM projects WHERE id = {db.ph}", [project_id])
        if project is None:
            raise ValueError(f"项目不存在: {project_id}")
        run_pipeline(
            db,
            settings,
            project=project,
            query=query,
            sources=sources or ["arxiv"],
            max_results=max_results,
            download_pdfs=download_pdfs,
            pdf_limit=pdf_limit,
            use_llm=use_llm,
        )
    if mode == "auto":
        selected = DEFAULT_FRAMEWORK
    else:
        selected = framework or {}
    if mode == "custom" and not selected:
        raise ValueError("custom 模式必须提供至少一个研究框架问题")

    params: list[Any] = [project_id]
    paper_filter = ""
    if paper_ids:
        marks = ", ".join([db.ph] * len(paper_ids))
        paper_filter = f" AND p.id IN ({marks})"
        params.extend(paper_ids)
    params.append(max_chunks)
    chunks = db.query(
        f"SELECT c.id, c.paper_id, c.text, c.summary, p.title FROM chunks c "
        f"JOIN papers p ON p.id = c.paper_id JOIN projects_papers pp ON pp.paper_id = p.id "
        f"WHERE pp.project_id = {db.ph}{paper_filter} ORDER BY c.id LIMIT {db.ph}",
        params,
    )
    actual_papers = sorted({int(c["paper_id"]) for c in chunks})
    llm_used = False
    if use_llm and settings.llm_enabled and chunks:
        try:
            from .llm.client import LLMClient

            context = "\n\n".join(
                f"[chunk_id={c['id']} paper_id={c['paper_id']} title={c['title']}]\n{c['text'][:1800]}"
                for c in chunks
            )
            framework_text = "\n".join(f"- {k}: {v}" for k, v in selected.items())
            prompt = (
                f"研究问题：{_project_question(db, project_id)}\n\n"
                f"请严格按以下框架分析文献，并区分证据与推断：\n{framework_text}\n\n"
                f"文献片段：\n{context}\n\n"
                "输出清晰的分节 Markdown；每个关键结论标注 [paper_id/chunk_id]。"
            )
            analysis = LLMClient(settings).complete(
                prompt,
                system="你是严谨的文献综述研究助手。不得编造文献中不存在的结论。",
                max_tokens=6000,
            )
            result = {"analysis": analysis, "framework": selected}
            llm_used = True
        except Exception as exc:  # LLM 失败不阻断导入文献研究
            logger.warning("框架研究 LLM 失败，回退规则草稿: {}", exc)
            result = _deterministic_result(selected, chunks)
    else:
        result = _deterministic_result(selected, chunks)

    research_id = db.insert(
        f"INSERT INTO research_runs (project_id, mode, framework, paper_ids, result, status, completed_at) "
        f"VALUES ({db.ph}, {db.ph}, {db.ph}, {db.ph}, {db.ph}, {db.ph}, CURRENT_TIMESTAMP)",
        [
            project_id,
            mode,
            db.dumps(selected),
            db.dumps(actual_papers),
            db.dumps(result),
            "completed",
        ],
    )
    return {
        "research_id": research_id,
        "project_id": project_id,
        "mode": mode,
        "framework": selected,
        "paper_ids": actual_papers,
        "papers_used": len(actual_papers),
        "chunks_used": len(chunks),
        "result": result,
        "llm_used": llm_used,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


def _project_question(db: Database, project_id: int) -> str:
    row = db.query_one(f"SELECT question FROM projects WHERE id = {db.ph}", [project_id])
    return row["question"] if row else "未提供"
