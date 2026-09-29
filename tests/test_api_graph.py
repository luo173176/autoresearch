"""图谱 API + CLI 集成测试。"""
import pytest
from fastapi.testclient import TestClient

from autoresearch.api.main import create_app
from autoresearch.cli import run_graph

from test_graph_builder import CHUNK_NEG, CHUNK_POS, _seed_project


@pytest.fixture()
def graph_project(db):
    return _seed_project(db, [CHUNK_POS, CHUNK_NEG])


def test_api_build_and_get_graph(test_settings, graph_project):
    client = TestClient(create_app(test_settings))
    pid = graph_project

    resp = client.post(f"/projects/{pid}/graph", json={"use_llm": False})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["chunks_processed"] == 2
    assert body["llm_used"] is False
    assert body["contradictions"] >= 1
    assert body["by_type"].get("method", 0) >= 2

    graph = client.get(f"/projects/{pid}/graph").json()
    assert graph["nodes"] and graph["links"]


def test_api_graph_errors(test_settings, graph_project):
    client = TestClient(create_app(test_settings))
    assert client.post("/projects/999/graph", json={}).status_code == 404
    assert client.get("/projects/999/graph").status_code == 404

    empty = client.post("/projects", json={"name": "e", "question": "q"}).json()["id"]
    assert client.post(f"/projects/{empty}/graph", json={}).status_code == 409  # 无 chunks


def test_cli_graph(test_settings, graph_project, capsys, tmp_path):
    export = tmp_path / "artifacts" / "g.json"
    assert run_graph(project=graph_project, use_llm=False, export=str(export),
                     settings=test_settings) == 0
    out = capsys.readouterr().out
    assert '"contradictions"' in out
    assert export.exists()

    # 缺省项目 = 最新；再跑一次应幂等
    assert run_graph(use_llm=False, settings=test_settings) == 0
