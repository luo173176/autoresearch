"""报告生成与评估指标测试。"""
import pytest

from autoresearch.experiments import create_experiment, run_experiment
from autoresearch.eval.metrics import (
    experiment_success_rate,
    graph_coverage,
    hypothesis_traceability,
    literature_parse_success_rate,
    pipeline_summary,
)
from autoresearch.reporting import generate_report

from test_graph_builder import CHUNK_COOC, CHUNK_NEG, CHUNK_POS, _seed_project
from test_hypotheses import graph_project  # noqa: F401


@pytest.fixture()
def fast_settings(test_settings):
    return test_settings.model_copy(update={
        "experiment_datasets": "iris", "experiment_folds": 3,
        "experiment_seeds": "0,1", "experiment_timeout": 300,
        "sandbox_enabled": False,
    })


@pytest.fixture()
def full_project(db, graph_project, fast_settings):  # noqa: F811
    """假设 → 实验 → 执行 的完整项目。"""
    from autoresearch.hypotheses import generate_hypotheses

    generate_hypotheses(db, project_id=graph_project, use_llm=False)
    hyp = db.query_one(
        f"SELECT id FROM hypotheses WHERE project_id = {db.ph} ORDER BY novelty DESC LIMIT 1",
        [graph_project],
    )
    created = create_experiment(db, fast_settings, hypothesis_id=hyp["id"])
    run_experiment(db, fast_settings, experiment_id=created["experiment_id"])
    return graph_project


def test_generate_report_with_citations(db, full_project):
    result = generate_report(db, project_id=full_project)
    content = result["content"]
    assert "## 摘要" in content and "## 参考文献" in content
    assert result["citations_count"] >= 1
    # 引用准确性（结构性）：正文引用编号不超过参考文献数量，且逐条可对应
    import re

    refs = re.findall(r"^\[(\d+)\] ", content, re.M)
    assert refs == [str(i) for i in range(1, result["citations_count"] + 1)]
    # 实验结果表格进入正文
    assert "| 实验 | 数据集 | 指标 |" in content
    # 报告已入库
    row = db.query_one(f"SELECT * FROM reports WHERE id = {db.ph}", [result["report_id"]])
    assert row["status"] == "draft" and row["citations"]


def test_generate_report_missing_project(db):
    with pytest.raises(LookupError):
        generate_report(db, project_id=999)


def test_eval_metrics(db, full_project):
    rate = literature_parse_success_rate(db, full_project)
    assert 0.0 <= rate <= 1.0
    cov = graph_coverage(db, {"method": ["logistic_regression"], "dataset": ["iris"]})
    assert 0.0 <= cov["coverage"] <= 1.0
    trace = hypothesis_traceability(db, full_project)
    assert trace["count"] >= 3 and trace["traceability_rate"] == pytest.approx(1.0)
    exp_metrics = experiment_success_rate(db)
    assert exp_metrics["runs"] >= 1 and exp_metrics["completed_rate"] == pytest.approx(1.0)
    summary = pipeline_summary(db, full_project, {"method": ["bm25"]})
    assert set(summary) == {"project_id", "literature_parse_success_rate", "graph",
                            "hypotheses", "experiments"}
