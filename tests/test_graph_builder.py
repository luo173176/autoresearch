"""知识图谱构建测试：规则路径（无 LLM）+ LLM 桩路径 + 矛盾检测 + 幂等。"""
import pytest

from autoresearch.graph import build_graph
from autoresearch.graph import builder as builder_mod
from autoresearch.graph.builder import _extract_rules, _parse_llm_json

CHUNK_POS = (
    "Retrieval augmented generation improves exact match on Natural Questions by 5 points. "
    "BM25 remains a strong sparse baseline for first stage retrieval."
)
CHUNK_NEG = (
    "We find that retrieval augmented generation degrades performance without a reranker. "
    "Future work should explore better reranking fusion methods."
)
CHUNK_COOC = "We study the BM25 retrieval method.\n\nWe test on MS MARCO benchmark."


def _seed_project(db, chunks: list[str]) -> int:
    pid = db.insert(
        f"INSERT INTO projects (name, question) VALUES ({db.ph}, {db.ph})", ["g", "q"]
    )
    for text in chunks:
        paper_id = db.insert(
            f"INSERT INTO papers (title, authors) VALUES ({db.ph}, {db.ph})",
            [f"paper-{paper_seq()}", "[]"],
        )
        db.insert(
            f"INSERT INTO projects_papers (project_id, paper_id) VALUES ({db.ph}, {db.ph})",
            [pid, paper_id],
        )
        db.insert(
            f"INSERT INTO chunks (paper_id, text) VALUES ({db.ph}, {db.ph})",
            [paper_id, text],
        )
    return pid


_seq = {"n": 0}


def paper_seq() -> int:
    _seq["n"] += 1
    return _seq["n"]


def _row(db, sql, params=None):
    return db.query_one(sql, params)


def test_rule_extraction_entities():
    result = _extract_rules(CHUNK_POS + " " + CHUNK_NEG)
    names = {(e["name"].lower(), e["type"]) for e in result["entities"]}
    assert ("retrieval augmented generation", "method") in names
    assert ("bm25", "method") in names
    assert ("natural questions", "dataset") in names
    assert ("exact match", "metric") in names
    assert any(t == "finding" for _, t in names)
    assert any(t == "gap" for _, t in names)


def test_rule_relations_and_polarity():
    result = _extract_rules(CHUNK_POS + " " + CHUNK_NEG)
    rels = {(r["source"].lower(), r["type"], r["target"].lower()) for r in result["relations"]}
    assert ("retrieval augmented generation", "uses", "natural questions") in rels
    assert ("retrieval augmented generation", "measured_by", "exact match") in rels
    assert any(rt == "reports" for _, rt, _ in rels)
    assert any(rt == "addresses" for _, rt, _ in rels)
    pols = [e["meta"]["polarity"] for e in result["entities"] if e["type"] == "finding"]
    assert "pos" in pols and "neg" in pols


def test_build_graph_end_to_end(db):
    pid = _seed_project(db, [CHUNK_POS, CHUNK_NEG])
    summary = build_graph(db, project_id=pid)
    assert summary["chunks_processed"] == 2
    assert summary["by_type"].get("method", 0) >= 2  # RAG + reranking + BM25
    assert summary["findings"] == 2
    # 矛盾：同一方法（RAG）上一正一负
    assert summary["contradictions"] >= 1
    rel = _row(
        db,
        f"SELECT r.confidence, r.evidence FROM relations r "
        f"JOIN entities se ON se.id = r.source_entity_id "
        f"JOIN entities te ON te.id = r.target_entity_id "
        f"WHERE r.type = 'contradicts' AND se.type = 'finding' AND te.type = 'finding'",
    )
    assert rel and rel["evidence"]


def test_chunk_level_cooccurrence_weak_confidence(db):
    pid = _seed_project(db, [CHUNK_COOC])
    build_graph(db, project_id=pid)
    rel = _row(
        db,
        f"SELECT r.confidence FROM relations r "
        f"JOIN entities se ON se.id = r.source_entity_id "
        f"JOIN entities te ON te.id = r.target_entity_id "
        f"WHERE r.type = 'uses' AND se.name = 'BM25' AND te.name = 'MS MARCO'",
    )
    assert rel and rel["confidence"] == pytest.approx(0.3)


def test_idempotent_rebuild(db):
    pid = _seed_project(db, [CHUNK_POS, CHUNK_NEG])
    first = build_graph(db, project_id=pid)
    second = build_graph(db, project_id=pid)
    assert first["entities_created"] > 0 and first["relations_created"] > 0
    assert second["entities_created"] == 0
    assert second["relations_created"] == 0
    n_ev = _row(
        db,
        "SELECT COUNT(*) AS n FROM relations WHERE type = 'contradicts'",
    )
    assert n_ev["n"] == first["contradictions"]  # 证据未重复追加导致关系翻倍


def test_no_chunks_raises(db):
    pid = db.insert(
        f"INSERT INTO projects (name, question) VALUES ({db.ph}, {db.ph})", ["empty", "q"]
    )
    with pytest.raises(ValueError):
        build_graph(db, project_id=pid)


class FakeLLM:
    def __init__(self, outputs):
        self.outputs = outputs

    def complete(self, prompt, system=None, **kw):
        return self.outputs.pop(0)

    def batch_complete(self, prompts, system=None, **kw):
        return [self.outputs.pop(0) for _ in prompts]


def test_llm_path_stored(db, test_settings, monkeypatch):
    good = json_dumps({
        "entities": [{"name": "GraphRAG", "type": "method", "quote": "we use GraphRAG"}],
        "relations": [{"source": "GraphRAG", "source_type": "method", "target": "HotpotQA",
                       "target_type": "dataset", "type": "uses", "quote": "evaluated on HotpotQA",
                       "confidence": 0.9}],
    })
    monkeypatch.setattr(builder_mod, "_probe_llm", lambda settings: FakeLLM([good]))
    pid = _seed_project(db, ["We use GraphRAG on multi hop QA."])
    llm_on = test_settings.model_copy(update={"llm_enabled": True})
    summary = build_graph(db, llm_on, project_id=pid, use_llm=True)
    assert summary["llm_used"] is True
    row = _row(
        db,
        f"SELECT r.confidence, r.evidence FROM relations r "
        f"JOIN entities se ON se.id = r.source_entity_id "
        f"JOIN entities te ON te.id = r.target_entity_id "
        f"WHERE se.name = 'GraphRAG' AND te.name = 'HotpotQA' AND r.type = 'uses'",
    )
    assert row and row["confidence"] == pytest.approx(0.9)
    assert row["evidence"][0]["quote"] == "evaluated on HotpotQA"


def test_llm_malformed_falls_back_to_rules(db, test_settings, monkeypatch):
    monkeypatch.setattr(builder_mod, "_probe_llm", lambda settings: FakeLLM(["这不是JSON"]))
    pid = _seed_project(db, [CHUNK_POS])
    llm_on = test_settings.model_copy(update={"llm_enabled": True})
    summary = build_graph(db, llm_on, project_id=pid, use_llm=True)
    assert summary["llm_used"] is True  # 探测成功，但逐 chunk 回退
    row = _row(db, f"SELECT id FROM entities WHERE lower(name) = lower({db.ph}) AND type = 'method'",
               ["bm25"])
    assert row  # 规则路径兜底产出


def test_parse_llm_json_strips_fences():
    text = "```json\n" + json_dumps({"entities": [], "relations": []}) + "\n```"
    assert _parse_llm_json(text) is not None
    assert _parse_llm_json("完全没有 JSON") is None
    bad = _parse_llm_json(json_dumps({"entities": [{"name": "X", "type": "bad_type"}]}))
    assert bad["entities"] == []


def json_dumps(obj) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
