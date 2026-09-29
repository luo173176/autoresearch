"""知识图谱：构建（builder）与查询（query）。

用法：
    from autoresearch.graph import build_graph, export_graph
    summary = build_graph(db, settings, project_id=1)
"""
from .builder import build_graph
from .query import (
    build_networkx,
    contradictions,
    entity_stats,
    export_graph,
    gaps,
    neighbors,
    top_entities,
)

__all__ = [
    "build_graph", "entity_stats", "top_entities", "neighbors", "gaps",
    "contradictions", "export_graph", "build_networkx",
]
