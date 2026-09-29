"""实验执行 + 报告 API 集成测试 + CLI（experiment/run/report/watch）。"""
import pytest
from fastapi.testclient import TestClient

from autoresearch.api.main import create_app
from autoresearch.cli import run_auto, run_experiment_cmd, run_report, run_run, run_watch
from autoresearch.graph import build_graph
from autoresearch.hypotheses import generate_hypotheses

from test_graph_builder import CHUNK_COOC, CHUNK_NEG, CHUNK_POS, _seed_project
from test_api_literature import PAPER_A, PAPER_B  # 复用打桩数据


@pytest.fixture()
def fast_settings(test_settings):
    return test_settings.model_copy(update={
        "experiment_datasets": "iris", "experiment_folds": 3,
        "experiment_seeds": "0,1", "experiment_timeout": 300,
        "sandbox_enabled": False,
    })


@pytest.fixture()
def project_with_hypotheses(db, test_settings, monkeypatch):
    monkeypatch.setattr(
        "autoresearch.literature.search_all",
        lambda query, settings, sources=None, max_results=50, client=None: ([PAPER_A, PAPER_B], {}),
    )
    pid = _seed_project(db, [CHUNK_POS, CHUNK_NEG, CHUNK_COOC])
    build_graph(db, test_settings, project_id=pid)
    generate_hypotheses(db, test_settings, project_id=pid, use_llm=False)
    return pid


def test_api_full_loop(test_settings, fast_settings, db, project_with_hypotheses):
    client = TestClient(create_app(fast_settings))
    hyp = client.get(f"/projects/{project_with_hypotheses}/hypotheses").json()[0]

    created = client.post(f"/hypotheses/{hyp['id']}/experiments", json={})
    assert created.status_code == 201, created.text
    eid = created.json()["experiment_id"]

    run = client.post(f"/experiments/{eid}/run")
    assert run.status_code == 200, run.text
    assert run.json()["status"] == "completed"

    detail = client.get(f"/experiments/{eid}").json()
    assert detail["runs"] and detail["runs"][0]["status"] == "completed"

    report = client.post(f"/projects/{project_with_hypotheses}/report")
    assert report.status_code == 200, report.text
    rid = report.json()["report_id"]
    fetched = client.get(f"/reports/{rid}")
    assert fetched.status_code == 200 and "## 摘要" in fetched.json()["content"]

    assert client.post("/hypotheses/999/experiments").status_code == 404
    assert client.post("/experiments/999/run").status_code == 404
    assert client.get("/experiments/999").status_code == 404
    assert client.get("/reports/999").status_code == 404


def test_cli_experiment_run_report(db, fast_settings, project_with_hypotheses, capsys, tmp_path):
    assert run_experiment_cmd(run=True, settings=fast_settings) == 0  # 缺省取 top 假设并执行
    out = capsys.readouterr().out
    assert "已生成" in out and '"status": "completed"' in out

    assert run_run(1, settings=fast_settings) == 0  # 重跑实验 #1
    assert run_report(project=project_with_hypotheses, export=str(tmp_path / "r.md"),
                      settings=fast_settings) == 0
    assert (tmp_path / "r.md").exists()


def test_cli_watch_once(db, test_settings, monkeypatch, capsys):
    monkeypatch.setattr(
        "autoresearch.literature.search_all",
        lambda query, settings, sources=None, max_results=50, client=None: ([PAPER_A], {}),
    )
    pid = _seed_project(db, [CHUNK_POS])
    assert run_watch(project=pid, once=True, settings=test_settings) == 0
    out = capsys.readouterr().out
    assert "轮次完成" in out
    assert db.scalar(f"SELECT COUNT(*) FROM hypotheses WHERE project_id = {db.ph}", [pid]) >= 1


def test_cli_auto_end_to_end(db, fast_settings, monkeypatch, capsys):
    """一键命令：一个问题 → 全部产出（项目/图谱/假设/实验/报告）。"""
    from autoresearch.literature.search import dedupe_key
    from autoresearch.models import Paper

    rich_papers = [
        Paper(id=0, title="Reranking Helps RAG", authors=["Eve"], year=2024, venue="arXiv",
              abstract="Retrieval augmented generation improves exact match on Natural Questions by 5 points.",
              url="http://x/1", dedupe_key=dedupe_key("Reranking Helps RAG", 2024),
              metadata={"source": "arxiv"}),
        Paper(id=0, title="Reranking Hurts Without Fusion", authors=["Fox"], year=2023,
              venue="arXiv",
              abstract=("We find that retrieval augmented generation degrades performance "
                        "without a reranker. Future work should explore better fusion."),
              url="http://x/2", dedupe_key=dedupe_key("Reranking Hurts Without Fusion", 2023),
              metadata={"source": "arxiv"}),
    ]
    monkeypatch.setattr(
        "autoresearch.literature.search_all",
        lambda query, settings, sources=None, max_results=50, client=None: (rich_papers, {}),
    )
    assert run_auto("does reranking improve RAG QA", max_results=10, settings=fast_settings) == 0
    out = capsys.readouterr().out
    assert "完成" in out
    assert db.scalar("SELECT COUNT(*) FROM hypotheses") >= 1
    assert db.scalar("SELECT COUNT(*) FROM runs") >= 1
    assert db.scalar("SELECT COUNT(*) FROM reports") >= 1
    assert (fast_settings.data_dir / "artifacts").exists()
