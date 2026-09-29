"""图谱查询：统计、邻居、缺口/矛盾清单、JSON 导出（可视化用）、NetworkX 构建。"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from ..db import Database


def entity_stats(db: Database) -> dict[str, int]:
    rows = db.query("SELECT type, COUNT(*) AS n FROM entities GROUP BY type")
    return {r["type"]: r["n"] for r in rows}


def top_entities(db: Database, limit: int = 20, etype: str | None = None) -> list[dict]:
    """按关系度排序的头部实体。"""
    where = f"WHERE e.type = {db.ph}" if etype else ""
    params = [etype] if etype else []
    rows = db.query(
        f"SELECT e.id, e.name, e.type, "
        f"(SELECT COUNT(*) FROM relations r WHERE r.source_entity_id = e.id"
        f" OR r.target_entity_id = e.id) AS degree "
        f"FROM entities e {where} "
        f"ORDER BY degree DESC, e.id ASC LIMIT {int(limit)}",
        params,
    )
    return rows


def neighbors(db: Database, name: str, etype: str | None = None,
              rel_type: str | None = None, limit: int = 50) -> list[dict]:
    """给定实体的邻居（双向）。"""
    conds = [f"(se.name = {db.ph} OR te.name = {db.ph})"]
    params: list = [name, name]
    if etype:
        conds.append(f"(se.type = {db.ph} OR te.type = {db.ph})")
        params += [etype, etype]
    if rel_type:
        conds.append(f"r.type = {db.ph}")
        params.append(rel_type)
    where = " AND ".join(conds)
    return db.query(
        f"SELECT se.name AS source, se.type AS source_type, r.type AS relation, "
        f"te.name AS target, te.type AS target_type, r.confidence "
        f"FROM relations r "
        f"JOIN entities se ON se.id = r.source_entity_id "
        f"JOIN entities te ON te.id = r.target_entity_id "
        f"WHERE {where} ORDER BY r.confidence DESC LIMIT {int(limit)}",
        params,
    )


def gaps(db: Database, limit: int = 50) -> list[dict]:
    return db.query(
        f"SELECT e.id, e.name, e.metadata, "
        f"(SELECT COUNT(*) FROM relations r WHERE r.target_entity_id = e.id) AS n_methods "
        f"FROM entities e WHERE e.type = 'gap' ORDER BY e.id DESC LIMIT {int(limit)}"
    )


def contradictions(db: Database, limit: int = 50) -> list[dict]:
    return db.query(
        f"SELECT se.name AS finding_a, te.name AS finding_b, r.confidence, r.evidence "
        f"FROM relations r "
        f"JOIN entities se ON se.id = r.source_entity_id "
        f"JOIN entities te ON te.id = r.target_entity_id "
        f"WHERE r.type = 'contradicts' ORDER BY r.id DESC LIMIT {int(limit)}"
    )


def project_entity_names(db: Database, project_id: int) -> set[str]:
    rows = db.query(
        f"SELECT c.entities FROM chunks c "
        f"JOIN projects_papers pp ON pp.paper_id = c.paper_id "
        f"WHERE pp.project_id = {db.ph}",
        [project_id],
    )
    names: set[str] = set()
    for r in rows:
        for n in (r.get("entities") or []):
            names.add(n)
    return names


def export_graph(db: Database, project_id: int, path: Path | str | None = None) -> dict:
    """导出项目子图 {nodes, links}；节点含类型与度数，边含类型/置信度/证据数。"""
    names = project_entity_names(db, project_id)
    links: list[dict] = []
    if names:
        all_rels = db.query(
            f"SELECT se.name AS source, se.type AS source_type, r.type AS relation, "
            f"r.confidence, r.evidence, te.name AS target, te.type AS target_type "
            f"FROM relations r "
            f"JOIN entities se ON se.id = r.source_entity_id "
            f"JOIN entities te ON te.id = r.target_entity_id"
        )
        name_types = {n.lower() for n in names}
        for r in all_rels:
            if r["source"].lower() in name_types and r["target"].lower() in name_types:
                links.append({
                    "source": r["source"], "target": r["target"],
                    "type": r["relation"], "confidence": r["confidence"],
                    "n_evidence": len(r.get("evidence") or []),
                })
    degree = Counter()
    for lk in links:
        degree[lk["source"]] += 1
        degree[lk["target"]] += 1
    nodes = [{"id": n, "degree": degree.get(n, 0)} for n in sorted(names)]
    data = {"project_id": project_id, "nodes": nodes, "links": links}
    if path is not None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def build_networkx(db: Database, project_id: int | None = None):
    """构建 NetworkX 有向图（可选按项目过滤），节点/边带属性。"""
    import networkx as nx

    graph = nx.DiGraph()
    if project_id is not None:
        data = export_graph(db, project_id)
        for node in data["nodes"]:
            graph.add_node(node["id"], degree=node["degree"])
        for lk in data["links"]:
            graph.add_edge(lk["source"], lk["target"], type=lk["type"],
                           confidence=lk["confidence"])
        return graph
    for e in db.query("SELECT name, type, metadata FROM entities"):
        graph.add_node(e["name"], type=e["type"])
    for r in db.query(
        f"SELECT se.name AS source, te.name AS target, r.type, r.confidence "
        f"FROM relations r JOIN entities se ON se.id = r.source_entity_id "
        f"JOIN entities te ON te.id = r.target_entity_id"
    ):
        graph.add_edge(r["source"], r["target"], type=r["type"], confidence=r["confidence"])
    return graph
