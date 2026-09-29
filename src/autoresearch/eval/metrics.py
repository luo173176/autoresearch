"""评估指标：对平台流水线的产出做可量化验收（纯函数，便于测试）。"""
from __future__ import annotations

from ..db import Database


def literature_parse_success_rate(db: Database, project_id: int) -> float:
    """文献可用文本率（有 abstract 或已解析 pdf 的论文占比）。"""
    rows = db.query(
        f"SELECT p.abstract, p.pdf_path FROM papers p "
        f"JOIN projects_papers pp ON pp.paper_id = p.id WHERE pp.project_id = {db.ph}",
        [project_id],
    )
    if not rows:
        return 0.0
    usable = sum(1 for r in rows if r.get("abstract") or r.get("pdf_path"))
    return usable / len(rows)


def graph_coverage(db: Database, checklist: dict[str, list[str]]) -> dict:
    """图谱对核心实体清单的覆盖率。"""
    names = {(r["name"] or "").lower() for r in db.query("SELECT name FROM entities")}
    detail = {}
    total_hit = total = 0
    for cat, items in checklist.items():
        hits = [x for x in items if x.lower() in names]
        detail[cat] = {"hit": len(hits), "total": len(items),
                       "missing": [x for x in items if x.lower() not in names]}
        total_hit += len(hits)
        total += len(items)
    return {"coverage": total_hit / total if total else 0.0, "detail": detail}


def hypothesis_traceability(db: Database, project_id: int) -> dict:
    """假设的溯源率与可验证性齐备率。"""
    rows = db.query(f"SELECT metadata, testability FROM hypotheses WHERE project_id = {db.ph}",
                    [project_id])
    if not rows:
        return {"count": 0, "traceability_rate": 0.0, "testability_rate": 0.0}
    traced = sum(1 for r in rows
                 if (r.get("metadata") or {}).get("relation_ids")
                 or (r.get("metadata") or {}).get("entity_ids"))
    testable = sum(1 for r in rows
                   if (r.get("testability") or {}).get("datasets")
                   and (r.get("testability") or {}).get("metrics")
                   and (r.get("testability") or {}).get("baseline"))
    return {"count": len(rows), "traceability_rate": traced / len(rows),
            "testability_rate": testable / len(rows)}


def experiment_success_rate(db: Database) -> dict:
    """run 完成率与提升占比。"""
    runs = db.query("SELECT status, metrics FROM runs")
    if not runs:
        return {"runs": 0, "completed_rate": 0.0, "improvement_rate": 0.0}
    completed = [r for r in runs if r.get("status") == "completed"]
    improvements = 0
    for r in completed:
        analysis = ((r.get("metrics") or {}).get("analysis") or {})
        if analysis.get("overall") == "improvement":
            improvements += 1
    return {"runs": len(runs),
            "completed_rate": len(completed) / len(runs),
            "improvement_rate": improvements / len(completed) if completed else 0.0}


def pipeline_summary(db: Database, project_id: int, checklist: dict[str, list[str]] | None = None) -> dict:
    return {
        "project_id": project_id,
        "literature_parse_success_rate": round(literature_parse_success_rate(db, project_id), 4),
        "graph": graph_coverage(db, checklist) if checklist else None,
        "hypotheses": hypothesis_traceability(db, project_id),
        "experiments": experiment_success_rate(db),
    }
