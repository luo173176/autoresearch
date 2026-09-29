"""在线验收（阶段 3）：对真实图谱生成 50 条假设，输出溯源检查 + 抽查样本。

用法: python tools/live_hypotheses.py [project_id] [max]
"""
import os
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
os.chdir(REPO)
os.environ.setdefault("AUTORESEARCH_SQLITE_PATH", str(REPO / "data" / "autoresearch.db"))
os.environ.setdefault("AUTORESEARCH_DATA_DIR", str(REPO / "data"))
os.environ.setdefault("AUTORESEARCH_LLM_CACHE_DIR", str(REPO / "data" / "cache" / "llm"))

from autoresearch.cli import main as cli_main  # noqa: E402
from autoresearch.config import get_settings  # noqa: E402
from autoresearch.db import Database  # noqa: E402


def main() -> int:
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    max_hyp = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    code = cli_main(["hypotheses", "--project", str(pid), "--max", str(max_hyp), "--no-llm"])

    db = Database(get_settings())
    rows = db.query(
        f"SELECT statement, rationale, testability, novelty, metadata FROM hypotheses "
        f"WHERE project_id = {db.ph} ORDER BY novelty DESC", [pid],
    )
    print("=" * 60)
    print(f"[验收] 库内假设: {len(rows)} 条")
    sources = Counter((r.get("metadata") or {}).get("source", "?") for r in rows)
    print(f"[验收] 来源分布: {dict(sources)}")
    traced = sum(1 for r in rows
                 if (r.get("metadata") or {}).get("relation_ids")
                 or (r.get("metadata") or {}).get("entity_ids"))
    print(f"[验收] 证据溯源率: {traced}/{len(rows)} = {traced / len(rows) * 100:.0f}%"
          if rows else "[验收] 无假设")
    testable = sum(1 for r in rows
                   if (r.get("testability") or {}).get("datasets")
                   and (r.get("testability") or {}).get("metrics")
                   and (r.get("testability") or {}).get("baseline"))
    print(f"[验收] testability 三要素齐备率: {testable}/{len(rows)}" if rows else "")
    print("-" * 60)
    print("[人工抽查样本] 按 novelty 排序前 10 条：")
    for i, r in enumerate(rows[:10], 1):
        t = r.get("testability") or {}
        meta = r.get("metadata") or {}
        print(f"\n#{i} [novelty={r['novelty']:.2f} 来源={meta.get('source')}]")
        print(f"  statement: {r['statement'][:150]}")
        print(f"  rationale: {(r['rationale'] or '')[:120]}")
        print(f"  datasets={t.get('datasets')} | metrics={t.get('metrics')} | baseline={t.get('baseline')}")
        print(f"  溯源: relation_ids={meta.get('relation_ids')} entity_ids={meta.get('entity_ids')}")
    return code


if __name__ == "__main__":
    sys.exit(main())
