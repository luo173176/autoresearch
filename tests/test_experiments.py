"""实验设计/代码生成/执行/分析测试：生成的代码包真实运行（iris 小数据集，秒级）。"""

import json

import pytest

from autoresearch.experiments import create_experiment, run_experiment
from autoresearch.experiments.analyzer import analyze_results

from test_graph_builder import CHUNK_COOC, CHUNK_NEG, CHUNK_POS, _seed_project
from test_hypotheses import graph_project  # noqa: F401  复用 fixture


@pytest.fixture()
def fast_settings(test_settings):
    return test_settings.model_copy(
        update={
            "experiment_datasets": "iris",
            "experiment_folds": 3,
            "experiment_seeds": "0,1",
            "experiment_timeout": 300,
            "sandbox_enabled": False,
            "execution_mode": "unsafe-local",  # 测试走快速本地执行器
        }
    )


def test_run_experiment_docker_path_mocked(db, test_settings, top_hypothesis_id, monkeypatch):
    """Docker 执行路径：mock 沙箱成功 → executor=docker。"""
    created = create_experiment(
        db,
        test_settings.model_copy(
            update={
                "experiment_datasets": "iris",
                "experiment_folds": 3,
                "experiment_seeds": "0,1",
                "sandbox_enabled": True,
            }
        ),
        hypothesis_id=top_hypothesis_id,
    )
    workspace = test_settings.data_dir / "experiments" / str(created["experiment_id"])

    def fake_sandboxed(ws, settings, **kwargs):
        # 沙箱内跑不出 sklearn → 直接落地一份 results.json 模拟成功
        import subprocess
        import sys

        subprocess.run([sys.executable, "main.py"], cwd=ws, check=True, capture_output=True)
        return {"exit_code": 0, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr("autoresearch.experiments.is_docker_available", lambda: True)
    monkeypatch.setattr("autoresearch.experiments.run_sandboxed", fake_sandboxed)
    result = run_experiment(
        db,
        test_settings.model_copy(update={"sandbox_enabled": True}),
        experiment_id=created["experiment_id"],
    )
    assert result["status"] == "completed"
    assert result["executor"] == "docker"
    assert (workspace / "results.json").exists()


@pytest.fixture()
def top_hypothesis_id(db, graph_project):  # noqa: F811
    from autoresearch.hypotheses import generate_hypotheses

    generate_hypotheses(db, project_id=graph_project, use_llm=False)
    row = db.query_one(
        f"SELECT id FROM hypotheses WHERE project_id = {db.ph} ORDER BY novelty DESC, id LIMIT 1",
        [graph_project],
    )
    return row["id"]


def test_design_from_hypothesis(test_settings, graph_project, top_hypothesis_id, db):
    from autoresearch.experiments.designer import design_from_hypothesis

    hyp = db.query_one(f"SELECT * FROM hypotheses WHERE id = {db.ph}", [top_hypothesis_id])
    design = design_from_hypothesis(hyp, test_settings)
    assert design["hypothesis_id"] == top_hypothesis_id
    assert design["baselines"] and design["proposed"]["estimator"]
    assert design["stat_test"]["name"] == "exact_sign_test"
    assert design["note"]  # 代理实验说明必须显式记录


def test_create_experiment_codegen(db, fast_settings, top_hypothesis_id):
    created = create_experiment(db, fast_settings, hypothesis_id=top_hypothesis_id)
    eid = created["experiment_id"]
    assert set(created["files"]) >= {"main.py", "config.json", "requirements.txt", "README.md"}
    assert (
        f"experiments{chr(92)}{eid}" in created["workspace"]
        or f"experiments/{eid}" in created["workspace"]
    )

    cfg = json.loads(
        (fast_settings.data_dir / "experiments" / str(eid) / "config.json").read_text(
            encoding="utf-8"
        )
    )
    assert cfg["experiment_id"] == eid and cfg["datasets"][0]["name"] == "iris"

    row = db.query_one(f"SELECT * FROM experiments WHERE id = {db.ph}", [eid])
    assert row["status"] == "designed"


def test_run_experiment_local_executes(db, fast_settings, top_hypothesis_id):
    created = create_experiment(db, fast_settings, hypothesis_id=top_hypothesis_id)
    result = run_experiment(db, fast_settings, experiment_id=created["experiment_id"])
    assert result["status"] == "completed", result.get("error", "")
    assert result["executor"] == "local"  # 本机无 Docker
    analysis = result["analysis"]
    assert analysis["per_item"] and analysis["overall"] in {"improvement", "degradation", "parity"}
    # runs 表已记录
    run = db.query_one(f"SELECT * FROM runs WHERE id = {db.ph}", [result["run_id"]])
    assert run["status"] == "completed"
    assert run["metrics"]["analysis"]["overall"] == analysis["overall"]


def test_run_experiment_retry_on_failure(db, fast_settings, top_hypothesis_id):
    created = create_experiment(db, fast_settings, hypothesis_id=top_hypothesis_id)
    ws = fast_settings.data_dir / "experiments" / str(created["experiment_id"])
    (ws / "main.py").write_text("raise SystemExit(2)\n", encoding="utf-8")  # 破坏代码
    result = run_experiment(db, fast_settings, experiment_id=created["experiment_id"], attempts=2)
    assert result["status"] == "failed"
    run = db.query_one(f"SELECT * FROM runs WHERE id = {db.ph}", [result["run_id"]])
    assert run["status"] == "failed" and "plan=" in (run["logs"] or "")


def test_analyze_results_unit():
    results = {
        "runs": [
            {
                "dataset": "iris",
                "comparison": {
                    "accuracy": {
                        "mean_baseline": 0.9,
                        "mean_proposed": 0.95,
                        "mean_diff": 0.05,
                        "sign_test_p": 0.03,
                        "std_proposed": 0.01,
                    }
                },
            }
        ]
    }
    analysis = analyze_results(results)
    assert analysis["per_item"][0]["verdict"] == "significant_improvement"
    assert analysis["overall"] == "improvement"
    assert analysis["suggestions"]


def test_missing_experiment_raises(db, fast_settings):
    with pytest.raises(LookupError):
        run_experiment(db, fast_settings, experiment_id=999)


def test_strict_mode_refuses_local_fallback(db, test_settings, top_hypothesis_id):
    created = create_experiment(db, test_settings, hypothesis_id=top_hypothesis_id)
    strict = test_settings.model_copy(
        update={
            "sandbox_enabled": False,
            "execution_mode": "strict",
        }
    )
    with pytest.raises(RuntimeError, match="严格执行模式要求 Docker 沙箱"):
        run_experiment(db, strict, experiment_id=created["experiment_id"])
