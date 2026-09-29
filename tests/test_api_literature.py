"""文献流水线 API + CLI 集成测试（search_all 打桩，不依赖外网）。"""
import pytest
from fastapi.testclient import TestClient

from autoresearch.api.main import create_app
from autoresearch.cli import run_literature
from autoresearch.literature.search import dedupe_key
from autoresearch.models import Paper

PAPER_A = Paper(
    id=0, title="Reranking Helps RAG", authors=["Eve"], year=2024, venue="arXiv",
    abstract="We study reranking effects on RAG accuracy.", url="http://x/1",
    dedupe_key=dedupe_key("Reranking Helps RAG", 2024),
    metadata={"source": "arxiv", "pdf_url": "http://x/1.pdf"},
)
PAPER_B = Paper(
    id=0, title="GNNs on Tables", authors=["Fox"], year=2023, venue="arXiv",
    abstract="We evaluate GNNs on tabular benchmarks.", url="http://x/2",
    dedupe_key=dedupe_key("GNNs on Tables", 2023),
    metadata={"source": "arxiv", "pdf_url": ""},
)


@pytest.fixture()
def stub_search(monkeypatch):
    calls = []

    def fake_search_all(query, settings, sources=None, max_results=50, client=None):
        calls.append(query)
        return [PAPER_A, PAPER_B], {}

    monkeypatch.setattr("autoresearch.literature.search_all", fake_search_all)
    return calls


def test_api_literature_pipeline(test_settings, db, stub_search):
    client = TestClient(create_app(test_settings))
    created = client.post(
        "/projects",
        json={"name": "文献测试", "question": "Does reranking help RAG?"},
    )
    assert created.status_code == 201
    pid = created.json()["id"]

    resp = client.post(f"/projects/{pid}/literature", json={"max_results": 5})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # query 缺省时取项目研究问题
    assert stub_search == ["Does reranking help RAG?"]
    assert body["papers_found"] == 2
    assert body["papers_new"] == 2
    assert body["chunks_created"] == 2  # 两篇论文各有摘要 → 各 1 chunk
    assert body["by_source"] == {"arxiv": 2}
    assert body["elapsed_ms"] >= 0

    papers = client.get(f"/projects/{pid}/papers").json()
    assert {p["title"] for p in papers} == {"Reranking Helps RAG", "GNNs on Tables"}
    assert papers[0]["metadata"]["source"] == "arxiv"


def test_api_literature_unknown_project(test_settings, db, stub_search):
    client = TestClient(create_app(test_settings))
    assert client.post("/projects/999/literature", json={}).status_code == 404
    assert client.get("/projects/999/papers").status_code == 404


def test_cli_literature_creates_project(test_settings, db, stub_search, capsys):
    assert run_literature("graph neural networks", settings=test_settings, use_llm=False) == 0
    out = capsys.readouterr().out
    assert '"papers_found": 2' in out
    # 项目自动创建 + 论文入库 + 摘要 chunk
    assert db.scalar("SELECT COUNT(*) FROM projects") == 1
    assert db.scalar("SELECT COUNT(*) FROM papers") == 2
    assert db.scalar("SELECT COUNT(*) FROM chunks") == 2


def test_cli_literature_existing_project(test_settings, db, stub_search):
    pid = db.insert(
        f"INSERT INTO projects (name, question) VALUES ({db.ph}, {db.ph})", ["p", "pq"]
    )
    assert run_literature("some query", project=pid, settings=test_settings) == 0
    assert db.scalar("SELECT COUNT(*) FROM projects") == 1  # 未新建项目
