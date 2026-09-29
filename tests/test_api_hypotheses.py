"""假设生成 API + CLI 集成测试。"""
import pytest
from fastapi.testclient import TestClient

from autoresearch.api.main import create_app
from autoresearch.cli import run_hypotheses
from autoresearch.graph import build_graph

from test_graph_builder import CHUNK_COOC, CHUNK_NEG, CHUNK_POS, _seed_project


@pytest.fixture()
def graph_ready(db):
    pid = _seed_project(db, [CHUNK_POS, CHUNK_NEG, CHUNK_COOC])
    build_graph(db, project_id=pid)
    return pid


def test_api_generate_and_list(test_settings, graph_ready):
    client = TestClient(create_app(test_settings))
    resp = client.post(f"/projects/{graph_ready}/hypotheses", json={"max_hypotheses": 20})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["generated"] >= 3 and body["stored"] >= 3
    assert body["llm_used"] is False

    rows = client.get(f"/projects/{graph_ready}/hypotheses").json()
    assert len(rows) == body["stored"]
    assert {"statement", "testability", "novelty", "metadata"} <= set(rows[0])


def test_api_errors(test_settings, graph_ready):
    client = TestClient(create_app(test_settings))
    assert client.post("/projects/999/hypotheses", json={}).status_code == 404
    assert client.get("/projects/999/hypotheses").status_code == 404
    # 空图谱项目 → 409
    empty = client.post("/projects", json={"name": "e", "question": "q"}).json()["id"]
    assert client.post(f"/projects/{empty}/hypotheses", json={}).status_code == 409


def test_cli_hypotheses(test_settings, graph_ready, capsys):
    assert run_hypotheses(project=graph_ready, settings=test_settings) == 0
    out = capsys.readouterr().out
    assert '"stored"' in out
    assert "Top1" in out
    # 幂等重跑
    assert run_hypotheses(project=graph_ready, use_llm=False, settings=test_settings) == 0
