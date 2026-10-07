from fastapi.testclient import TestClient

from autoresearch.api.main import create_app


def test_user_imported_paper_supports_auto_and_custom_research(test_settings, db):
    with TestClient(create_app(test_settings)) as client:
        project = client.post(
            "/projects", json={"name": "manual-study", "question": "如何评价检索增强生成？"}
        ).json()
        project_id = project["id"]
        imported = client.post(
            f"/projects/{project_id}/papers/import",
            json={
                "title": "A user supplied paper",
                "authors": ["Researcher"],
                "year": 2025,
                "abstract": "This paper studies retrieval augmented generation.",
                "text": "We evaluate retrieval quality and generation faithfulness. " * 30,
            },
        )
        assert imported.status_code == 201
        paper_id = imported.json()["id"]
        assert client.get(f"/projects/{project_id}/papers").json()[0]["id"] == paper_id

        automatic = client.post(
            f"/projects/{project_id}/research",
            json={"mode": "auto", "use_llm": False},
        )
        assert automatic.status_code == 200
        auto = automatic.json()
        assert auto["papers_used"] == 1
        assert auto["llm_used"] is False
        assert "gaps" in auto["framework"]

        custom = client.post(
            f"/projects/{project_id}/research",
            json={
                "mode": "custom",
                "use_llm": False,
                "paper_ids": [paper_id],
                "framework": {
                    "evidence": "只提取支持结论的原文证据。",
                    "reproducibility": "评价数据、代码和实验是否可复现。",
                },
            },
        )
        assert custom.status_code == 200
        result = custom.json()
        assert result["mode"] == "custom"
        assert set(result["framework"]) == {"evidence", "reproducibility"}
        assert client.get(f"/projects/{project_id}/research").json()


def test_custom_research_requires_framework(test_settings, db):
    with TestClient(create_app(test_settings)) as client:
        project = client.post("/projects", json={"name": "empty", "question": "q"}).json()
        response = client.post(
            f"/projects/{project['id']}/research",
            json={"mode": "custom", "use_llm": False},
        )
        assert response.status_code == 400
