"""在线验收（阶段 2）：对真实文献库构建知识图谱，输出统计 + 核心方法覆盖率。

用法: python tools/live_graph.py [project_id]
"""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
os.chdir(REPO)
os.environ.setdefault("AUTORESEARCH_SQLITE_PATH", str(REPO / "data" / "autoresearch.db"))
os.environ.setdefault("AUTORESEARCH_DATA_DIR", str(REPO / "data"))
os.environ.setdefault("AUTORESEARCH_LLM_CACHE_DIR", str(REPO / "data" / "cache" / "llm"))

from autoresearch.cli import main as cli_main  # noqa: E402
from autoresearch.config import get_settings  # noqa: E402
from autoresearch.db import Database  # noqa: E402
from autoresearch.graph.query import (  # noqa: E402
    build_networkx,
    contradictions,
    export_graph,
    gaps,
    top_entities,
)

# RAG 生态核心方法/数据集/指标清单（覆盖率检查基准）
CORE_CHECKLIST = {
    "method": ["retrieval augmented generation", "dense retrieval", "bm25", "reranking",
               "fine-tuning", "in-context learning", "chain-of-thought", "prompt engineering",
               "LoRA", "instruction tuning", "knowledge distillation", "cross-encoder",
               "transformer", "semantic search"],
    "dataset": ["natural questions", "triviaqa", "ms marco", "hotpotqa", "squad", "mmlu",
                "gsm8k", "fever", "pubmedqa", "kilt"],
    "metric": ["accuracy", "exact match", "f1", "rouge", "bertscore", "ndcg", "mrr",
               "perplexity", "hallucination rate", "faithfulness"],
}


def main() -> int:
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    code = cli_main(["graph", "--project", str(pid), "--no-llm",
                     "--export", f"data/artifacts/graph_project{pid}.json"])

    db = Database(get_settings())
    entities = db.query("SELECT name, type FROM entities")
    by_lower = {(e["name"] or "").lower() for e in entities}
    print("=" * 60)
    total_hit = total_core = 0
    for cat, names in CORE_CHECKLIST.items():
        hits = [n for n in names if n in by_lower]
        misses = [n for n in names if n not in by_lower]
        total_hit += len(hits)
        total_core += len(names)
        print(f"[覆盖率] {cat}: {len(hits)}/{len(names)} = {len(hits) / len(names) * 100:.0f}%"
              f"  缺失: {misses if misses else '无'}")
    print(f"[覆盖率] 总计: {total_hit}/{total_core} = {total_hit / total_core * 100:.0f}%")

    top = top_entities(db, limit=8)
    print("[Top 实体]", [(r["name"][:36], r["degree"]) for r in top])
    g = gaps(db)
    print(f"[研究缺口] {len(g)} 条，示例: {[r['name'][:48] for r in g[:3]]}")
    c = contradictions(db)
    print(f"[矛盾] {len(c)} 对，示例: {[r['finding_a'][:40] for r in c[:2]]}")
    data = export_graph(db, pid)
    print(f"[子图] {len(data['nodes'])} 节点 / {len(data['links'])} 边 → data/artifacts/graph_project{pid}.json")
    graph = build_networkx(db, pid)
    deg = sorted(graph.degree, key=lambda kv: -kv[1])[:3]
    print(f"[NetworkX] 节点 {graph.number_of_nodes()} 边 {graph.number_of_edges()} | "
          f"度数 top3: {deg}")
    return code


if __name__ == "__main__":
    sys.exit(main())
