"""端到端评估：对 eval/questions.jsonl 逐题跑通全流水线并输出指标报告（需外网）。

用法: python -m autoresearch.eval.run_eval --max-questions 3
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from loguru import logger

from ..config import get_settings
from ..db import Database
from ..eval.metrics import pipeline_summary
from ..graph import build_graph
from ..hypotheses import generate_hypotheses
from ..literature import run_pipeline

CORE_CHECKLIST = {
    "method": ["retrieval augmented generation", "dense retrieval", "bm25", "reranking",
               "fine-tuning", "in-context learning", "chain-of-thought"],
    "dataset": ["natural questions", "triviaqa", "ms marco", "hotpotqa", "squad"],
    "metric": ["accuracy", "exact match", "f1", "rouge", "ndcg", "mrr"],
}


def run_eval(questions_path: Path | None = None, max_questions: int = 3,
             max_results: int = 20, settings=None) -> dict:
    settings = settings or get_settings()
    settings.ensure_dirs()
    questions_path = questions_path or Path(__file__).resolve().parents[3] / "eval" / "questions.jsonl"
    db = Database(settings)
    db.migrate()

    questions = [json.loads(line) for line in
                 questions_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    questions = questions[:max_questions]
    out = {"started_at": time.strftime("%Y-%m-%d %H:%M:%S"), "results": []}
    for q in questions:
        logger.info("评估问题 {}: {}", q.get("id"), q.get("question"))
        pid = db.insert(
            f"INSERT INTO projects (name, question, domain) VALUES ({db.ph}, {db.ph}, {db.ph})",
            [f"eval-{q.get('id')}", q["question"], q.get("domain", "general")],
        )
        project = db.query_one(f"SELECT * FROM projects WHERE id = {db.ph}", [pid])
        lit = run_pipeline(db, settings, project=project, sources=["arxiv"],
                           max_results=max_results)
        graph = build_graph(db, settings, project_id=pid)
        hyp = generate_hypotheses(db, settings, project_id=pid, max_hypotheses=20)
        summary = pipeline_summary(db, pid, CORE_CHECKLIST)
        out["results"].append({
            "question_id": q.get("id"), "project_id": pid,
            "papers": lit["papers_found"], "chunks": lit["chunks_created"],
            "entities": graph["by_type"], "hypotheses": hyp["generated"],
            "metrics": summary,
        })
    out["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    dest = Path(__file__).resolve().parents[3] / "eval" / "results.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("评估完成: {}", dest)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="AutoResearch 端到端评估（需外网）")
    ap.add_argument("--max-questions", type=int, default=3)
    ap.add_argument("--max-results", type=int, default=20)
    args = ap.parse_args()
    out = run_eval(max_questions=args.max_questions, max_results=args.max_results)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    main()
