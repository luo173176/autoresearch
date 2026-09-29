"""分块与抽取测试：启发式路径（无 LLM）+ LLM 路径（假对象注入）。"""
from autoresearch.literature import extractor
from autoresearch.literature.extractor import (
    build_chunks,
    chunk_text,
    heuristic_keywords,
    heuristic_summary,
)

LONG = "This paper studies retrieval augmented generation. " * 60  # > max_chars


def test_chunk_text_paragraph_merging():
    text = "First paragraph about models.\n\nSecond paragraph about data.\n\nThird one."
    chunks = chunk_text(text, max_chars=1000, overlap=100)
    assert len(chunks) == 1
    assert "First paragraph" in chunks[0] and "Third one." in chunks[0]


def test_chunk_text_long_split_with_overlap():
    chunks = chunk_text(LONG, max_chars=200, overlap=50)
    assert len(chunks) >= 2
    assert all(len(c) <= 200 for c in chunks)
    # 相邻块有重叠：chunk[0] 的尾部出现在 chunk[1] 开头
    assert chunks[0][-50:] in chunks[1]


def test_chunk_text_empty():
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_heuristic_summary_and_keywords():
    text = ("Retrieval augmented generation combines search with language models. "
            "Attention mechanisms improve the fusion quality. ")
    summary = heuristic_summary(text)
    assert summary.startswith("Retrieval augmented generation")
    keywords = heuristic_keywords(text)
    assert keywords and all(" " not in k for k in keywords)
    assert "the" not in keywords  # 停用词已过滤


def test_build_chunks_heuristic(db, test_settings):
    pid = db.insert(
        f"INSERT INTO papers (title, authors) VALUES ({db.ph}, {db.ph})", ["T", "[]"]
    )
    created = build_chunks(db, test_settings, pid, [LONG], use_llm=True)  # llm_enabled=False → 启发式
    assert created == 1
    row = db.query_one(
        f"SELECT summary, keywords, metadata FROM chunks WHERE paper_id = {db.ph}", [pid]
    )
    assert row["summary"]
    assert isinstance(row["keywords"], list) and row["keywords"]
    assert row["metadata"]["enriched"] is False
    # 幂等：已有 chunk 的论文不再重复创建
    assert build_chunks(db, test_settings, pid, [LONG]) == 0
    assert db.scalar("SELECT COUNT(*) FROM chunks") == 1


def test_build_chunks_with_llm_stub(db, test_settings, monkeypatch):
    class FakeLLM:
        def batch_complete(self, prompts, system=None, **kwargs):
            assert system  # 提示词走系统角色
            return ["这是一段中文摘要。\nkw1, kw2, kw3"] * len(prompts)

    monkeypatch.setattr(extractor, "_probe_llm", lambda settings: FakeLLM())
    pid = db.insert(
        f"INSERT INTO papers (title, authors) VALUES ({db.ph}, {db.ph})", ["T2", "[]"]
    )
    llm_on = test_settings.model_copy(update={"llm_enabled": True})
    created = build_chunks(db, llm_on, pid, ["text one", "text two"], use_llm=True)
    assert created == 2
    rows = db.query(
        f"SELECT summary, keywords, metadata FROM chunks WHERE paper_id = {db.ph} ORDER BY id",
        [pid],
    )
    assert rows[0]["summary"] == "这是一段中文摘要。"
    assert rows[0]["keywords"] == ["kw1", "kw2", "kw3"]
    assert all(r["metadata"]["enriched"] is True for r in rows)
