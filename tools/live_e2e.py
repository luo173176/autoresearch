"""在线验收（阶段 4-6 端到端）：真实项目 上 假设→实验→执行→分析→报告。

用法: python tools/live_e2e.py [project_id]
"""
import json
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
from autoresearch.eval.metrics import pipeline_summary  # noqa: E402


def main() -> int:
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    db = Database(get_settings())
    db.migrate()
    top = db.query_one(
        f"SELECT id, statement, novelty FROM hypotheses WHERE project_id = {db.ph} "
        f"ORDER BY novelty DESC, id LIMIT 1", [pid],
    )
    if top is None:
        print("[e2e] 项目无假设，请先运行 tools/live_graph.py 与 live_hypotheses.py")
        return 1
    print(f"[e2e] 选中假设 #{top['id']} (novelty={top['novelty']:.2f}): {top['statement'][:100]}")

    code1 = cli_main(["experiment", "--hypothesis", str(top["id"]), "--run"])
    code2 = cli_main(["report", "--project", str(pid),
                      "--export", f"data/artifacts/report_project{pid}.md"])

    db2 = Database(get_settings())
    runs = db2.query("SELECT id, experiment_id, status, metrics FROM runs ORDER BY id DESC LIMIT 1")
    print("=" * 60)
    if runs and runs[0]["status"] == "completed":
        analysis = (runs[0].get("metrics") or {}).get("analysis") or {}
        print(f"[e2e] 最新 run #{runs[0]['id']} (实验#{runs[0]['experiment_id']}): completed")
        print(f"[e2e] 整体结论: {analysis.get('overall')} | "
              f"提升 {analysis.get('n_improvements')} / 下降 {analysis.get('n_degradations')}")
        for item in (analysis.get("per_item") or [])[:6]:
            print(f"  - {item['dataset']} · {item['metric']}: baseline={item['mean_baseline']} "
                  f"proposed={item['mean_proposed']} Δ={item['mean_diff']:+.4f} "
                  f"p={item['sign_test_p']} → {item['verdict']}")
    else:
        print(f"[e2e] 最新 run 状态: {runs[0]['status'] if runs else '无'}")
    summary = pipeline_summary(db2, pid)
    print(f"[e2e] 流水线指标: {json.dumps(summary, ensure_ascii=False)}")
    report_md = Path(REPO / "data" / "artifacts" / f"report_project{pid}.md")
    print(f"[e2e] 报告: {report_md} ({report_md.stat().st_size if report_md.exists() else 0} 字节)")
    print(f"[e2e] CLI 退出码: experiment={code1}, report={code2}")
    return 0 if (code1 == 0 and code2 == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
