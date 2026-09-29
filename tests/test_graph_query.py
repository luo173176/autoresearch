"""图谱查询接口测试：统计/邻居/导出/NetworkX。"""
from autoresearch.graph import build_graph
from autoresearch.graph.query import (
    build_networkx,
    contradictions,
    entity_stats,
    export_graph,
    gaps,
    neighbors,
    top_entities,
)

from test_graph_builder import CHUNK_NEG, CHUNK_POS, _seed_project


def test_stats_top_neighbors(db):
    pid = _seed_project(db, [CHUNK_POS, CHUNK_NEG])
    build_graph(db, project_id=pid)

    stats = entity_stats(db)
    assert stats.get("method", 0) >= 2
    assert stats.get("finding", 0) >= 2

    top = top_entities(db, limit=5)
    assert top and top[0]["degree"] >= 2
    assert any(r["name"] == "retrieval augmented generation" for r in top)

    rows = neighbors(db, "retrieval augmented generation")
    assert rows, "RAG 应有邻居关系"
    assert all(set(r) >= {"source", "relation", "target"} for r in rows)

    gaps_rows = gaps(db)
    assert gaps_rows and "future work" in gaps_rows[0]["name"].lower()

    cons = contradictions(db)
    assert cons and cons[0]["evidence"]


def test_export_graph_roundtrip(db, tmp_path):
    pid = _seed_project(db, [CHUNK_POS, CHUNK_NEG])
    build_graph(db, project_id=pid)

    data = export_graph(db, pid)
    assert data["project_id"] == pid
    assert data["nodes"] and data["links"]
    node_names = {n["id"] for n in data["nodes"]}
    assert "retrieval augmented generation" in {n.lower() for n in node_names} or \
        any(n.lower() == "retrieval augmented generation" for n in node_names)
    for lk in data["links"]:
        assert lk["source"] in node_names and lk["target"] in node_names
        assert lk["type"] in {"uses", "measured_by", "reports", "contradicts", "addresses",
                              "related_to"}

    out = tmp_path / "graph.json"
    export_graph(db, pid, out)
    assert out.exists() and '"nodes"' in out.read_text(encoding="utf-8")


def test_build_networkx(db):
    pid = _seed_project(db, [CHUNK_POS, CHUNK_NEG])
    build_graph(db, project_id=pid)
    graph = build_networkx(db, project_id=pid)
    assert graph.number_of_nodes() > 0 and graph.number_of_edges() > 0
    # 有向边带类型属性
    _, _, attrs = next(iter(graph.edges(data=True)))
    assert "type" in attrs

    full = build_networkx(db)
    assert full.number_of_nodes() >= graph.number_of_nodes()
