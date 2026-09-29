from fastapi.testclient import TestClient

from autoresearch.api.main import create_app


def test_health(test_settings):
    client = TestClient(create_app(test_settings))
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["backend"] == "sqlite"
    assert body["database"] is True
    assert body["app"] == "AutoResearch"


def test_project_crud(test_settings, db):
    client = TestClient(create_app(test_settings))
    resp = client.post(
        "/projects",
        json={
            "name": "演示项目",
            "question": "RAG 重排对 QA 的影响？",
            "domain": "IR",
            "budget": {"gpu_hours": 2},
        },
    )
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]
    assert resp.json()["budget"] == {"gpu_hours": 2}
    assert resp.json()["status"] == "active"

    assert client.get(f"/projects/{pid}").json()["name"] == "演示项目"
    assert client.get("/projects").json()[0]["id"] == pid
    assert client.get("/projects/99999").status_code == 404


def test_all_spec_endpoints_real(test_settings, db):
    """阶段 4-6 后规范内的全部端点均已实现（不再有 501 占位）。"""
    client = TestClient(create_app(test_settings))
    spec_paths = [
        ("POST", "/projects/1/literature"), ("POST", "/projects/1/graph"),
        ("POST", "/projects/1/hypotheses"), ("POST", "/hypotheses/1/experiments"),
        ("POST", "/experiments/1/run"), ("GET", "/experiments/1"),
        ("GET", "/reports/1"),
    ]
    for method, path in spec_paths:
        kwargs = {"json": {}} if method == "POST" else {}
        resp = getattr(client, method.lower())(path, **kwargs)
        assert resp.status_code != 501, f"{method} {path} 仍是占位实现"
