"""假设生成测试：规则路径三类来源 + ranker + LLM 桩 + 幂等 + API/CLI。"""
import pytest

from autoresearch.graph import build_graph
from autoresearch.hypotheses import generate_hypotheses, jaccard, rank, score_candidate
from autoresearch.hypotheses import generator as generator_mod
from autoresearch.hypotheses.ranker import _tokens

from test_graph_builder import CHUNK_COOC, CHUNK_NEG, CHUNK_POS, _seed_project


@pytest.fixture()
def graph_project(db):
    pid = _seed_project(db, [CHUNK_POS, CHUNK_NEG, CHUNK_COOC])
    build_graph(db, project_id=pid)
    return pid


def test_ranker_dedup_and_order():
    candidates = [
        {"statement": "假设 A 关于 reranking 提升准确率", "testability": {"datasets": ["d"], "metrics": ["m"], "baseline": "b"},
         "novelty": 0.5, "metadata": {"quotes": ["q1", "q2", "q3"]}},
        {"statement": "假设 A 关于 reranking 提升准确率", "testability": {"datasets": ["d"], "metrics": ["m"], "baseline": "b"},
         "novelty": 0.9, "metadata": {"quotes": ["q1", "q2", "q3"]}},
        {"statement": "完全不同的另一个关于 graph neural network 的假设", "testability": {"datasets": ["d"], "metrics": ["m"], "baseline": "b"},
         "novelty": 0.6, "metadata": {"quotes": []}},
    ]
    kept = rank(candidates, top_n=10)
    assert len(kept) == 2  # 前两条语句相同 → Jaccard 去重，保留得分更高者
    assert kept[0]["novelty"] == pytest.approx(0.9)


def test_score_and_jaccard():
    assert jaccard({"a", "b"}, {"a", "b"}) == 1.0
    assert jaccard({"a"}, {"b"}) == 0.0
    full = {"datasets": ["d"], "metrics": ["m"], "baseline": "b"}
    empty = {"datasets": [], "metrics": [], "baseline": None}
    assert score_candidate({"novelty": 0.5, "testability": full, "metadata": {}}) > \
        score_candidate({"novelty": 0.5, "testability": empty, "metadata": {}})
    assert _tokens("Hello 世界 123") == {"hello", "世界", "123"}


def test_generate_three_sources_with_traceability(db, graph_project):
    summary = generate_hypotheses(db, project_id=graph_project, use_llm=False)
    assert summary["generated"] >= 3
    assert {"contradiction", "gap", "combination"} <= set(summary["by_source"])
    assert summary["llm_used"] is False

    rows = db.query(f"SELECT * FROM hypotheses WHERE project_id = {db.ph}", [graph_project])
    assert len(rows) == summary["generated"]
    for row in rows:
        t = row["testability"]
        assert t["datasets"] and t["metrics"] and t["baseline"], "testability 三要素必须齐备"
        assert row["metadata"].get("source")
        # 证据溯源：relation_ids 或 entity_ids 至少一类非空
        assert row["metadata"].get("relation_ids") or row["metadata"].get("entity_ids")
    srcs = {r["metadata"]["source"] for r in rows}
    assert {"contradiction", "gap", "combination"} <= srcs
    # 矛盾类假设必须溯源到 contradicts 关系
    con = next(r for r in rows if r["metadata"]["source"] == "contradiction")
    assert con["metadata"]["relation_ids"]
    assert "retrieval augmented generation" in con["statement"].lower()


def test_generate_idempotent(db, graph_project):
    first = generate_hypotheses(db, project_id=graph_project, use_llm=False)
    second = generate_hypotheses(db, project_id=graph_project, use_llm=False)
    assert first["stored"] > 0
    assert second["stored"] == 0  # 相同 statement 命中 dedupe_key
    n = db.scalar(f"SELECT COUNT(*) FROM hypotheses WHERE project_id = {db.ph}", [graph_project])
    assert n == first["generated"]


def test_generate_without_graph_raises(db):
    pid = db.insert(f"INSERT INTO projects (name, question) VALUES ({db.ph}, {db.ph})", ["p", "q"])
    with pytest.raises(ValueError):
        generate_hypotheses(db, project_id=pid, use_llm=False)


class FakeLLM:
    def __init__(self, outputs):
        self.outputs = outputs

    def batch_complete(self, prompts, system=None, **kw):
        return [self.outputs[0]] * len(prompts)


def test_llm_enhancement_path(db, test_settings, monkeypatch, graph_project):
    fake = (
        '{"statement": "假设：在 Natural Questions 上以 exact match 评测，reranking 模块级联于 dense retrieval 之后可将 EM 提升 4 分（基线为无重排的 dense retrieval）。", '
        '"rationale": "图谱中二者共享 Natural Questions 且重排证据充分。", "novelty": 0.8}'
    )
    monkeypatch.setattr(generator_mod, "_probe_llm", lambda settings: FakeLLM([fake]))
    llm_on = test_settings.model_copy(update={"llm_enabled": True})
    summary = generate_hypotheses(db, llm_on, project_id=graph_project, max_hypotheses=50,
                                  use_llm=True)
    assert summary["llm_used"] is True
    row = db.query_one(
        f"SELECT statement, novelty FROM hypotheses WHERE project_id = {db.ph} "
        f"ORDER BY novelty DESC LIMIT 1", [graph_project],
    )
    assert "reranking" in row["statement"].lower()
    assert row["novelty"] == pytest.approx(0.8)


def test_llm_malformed_keeps_rules(db, test_settings, monkeypatch, graph_project):
    monkeypatch.setattr(generator_mod, "_probe_llm", lambda settings: FakeLLM(["不是JSON"]))
    llm_on = test_settings.model_copy(update={"llm_enabled": True})
    summary = generate_hypotheses(db, llm_on, project_id=graph_project, use_llm=True)
    assert summary["llm_used"] is True
    assert summary["generated"] >= 3  # 规则版本完整保留
