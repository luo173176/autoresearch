"""文献检索测试：httpx MockTransport 模拟三源 API，不依赖外网。"""
import httpx

from autoresearch.config import Settings
from autoresearch.literature import link_project_paper, store_paper
from autoresearch.literature.search import (
    arxiv_search,
    dedupe_key,
    pubmed_search,
    search_all,
    semantic_scholar_search,
)

ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <title>  Retrieval-Augmented
      Generation Survey </title>
    <summary>We survey RAG systems.
and their components.</summary>
    <published>2024-01-15T00:00:00Z</published>
    <author><name>Alice Chen</name></author>
    <author><name>Bob Liu</name></author>
    <link href="http://arxiv.org/abs/2401.00001v1" rel="alternate" type="text/html"/>
    <link href="http://arxiv.org/pdf/2401.00001v1" rel="related" type="application/pdf"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2402.00002v1</id>
    <title>Graph Neural Networks for Tables</title>
    <summary>We study GNN on tabular data.</summary>
    <published>2023-11-02T00:00:00Z</published>
    <author><name>Carol Wang</name></author>
  </entry>
</feed>
"""

S2_JSON = {
    "data": [
        {
            "title": "Retrieval-Augmented Generation Survey",
            "authors": [{"name": "Alice Chen"}],
            "year": 2024,
            "venue": "EMNLP",
            "abstract": "Survey of RAG.",
            "externalIds": {"ArXiv": "2401.00001", "DOI": "10.1000/x"},
            "url": "https://semanticscholar.org/paper/1",
            "paperId": "s2-1",
        }
    ]
}

PUBMED_ESEARCH = {"esearchresult": {"idlist": ["11111111"]}}
PUBMED_ESUMMARY = {
    "result": {
        "uids": ["11111111"],
        "11111111": {
            "title": "Reranking Improves Retrieval QA",
            "authors": [{"name": "Dan Wu"}],
            "pubdate": "2023 Jan 15",
            "source": "J Biomed Inform",
            "articleids": [{"idtype": "doi", "value": "10.1000/y"}],
        },
    }
}
PUBMED_EFETCH = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation><PMID>11111111</PMID>
      <Article><Abstract>
        <AbstractText>We show that reranking improves QA.</AbstractText>
        <AbstractText Label="METHODS">We test on two datasets.</AbstractText>
      </Abstract></Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""


def make_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def full_handler(request: httpx.Request) -> httpx.Response:
    host, path = request.url.host, request.url.path
    if host == "export.arxiv.org":
        return httpx.Response(200, text=ARXIV_XML)
    if host == "api.semanticscholar.org":
        return httpx.Response(200, json=S2_JSON)
    if host == "eutils.ncbi.nlm.nih.gov":
        if path.endswith("esearch.fcgi"):
            return httpx.Response(200, json=PUBMED_ESEARCH)
        if path.endswith("esummary.fcgi"):
            return httpx.Response(200, json=PUBMED_ESUMMARY)
        if path.endswith("efetch.fcgi"):
            return httpx.Response(200, text=PUBMED_EFETCH)
    return httpx.Response(404, text="not found")


def test_dedupe_key_normalization():
    assert dedupe_key("RAG  Survey", 2024) == dedupe_key("rag\tsurvey", 2024)
    assert dedupe_key("A", 2024) != dedupe_key("A", 2023)
    assert dedupe_key("A", 2024) != dedupe_key("B", 2024)


def test_arxiv_parse(test_settings):
    papers = arxiv_search("rag", test_settings, client=make_client(full_handler), max_results=10)
    assert len(papers) == 2
    first = papers[0]
    assert first.title == "Retrieval-Augmented Generation Survey"  # 空白归一化
    assert first.authors == ["Alice Chen", "Bob Liu"]
    assert first.year == 2024
    assert first.metadata["pdf_url"] == "http://arxiv.org/pdf/2401.00001v1"
    assert first.metadata["source"] == "arxiv"
    assert first.abstract.startswith("We survey RAG systems.")


def test_semantic_scholar_parse(test_settings):
    papers = semantic_scholar_search("rag", test_settings, client=make_client(full_handler))
    assert len(papers) == 1
    p = papers[0]
    assert p.venue == "EMNLP"
    assert p.metadata["doi"] == "10.1000/x"
    assert p.metadata["arxiv_id"] == "2401.00001"


def test_pubmed_full_flow(test_settings):
    papers = pubmed_search("reranking", test_settings, client=make_client(full_handler))
    assert len(papers) == 1
    p = papers[0]
    assert p.title == "Reranking Improves Retrieval QA"
    assert p.year == 2023
    assert p.abstract == "We show that reranking improves QA. We test on two datasets."
    assert p.metadata["pmid"] == "11111111"
    assert p.url.startswith("https://pubmed.ncbi.nlm.nih.gov/")


def test_search_all_merges_and_dedupes(test_settings):
    papers, errors = search_all("rag", test_settings, sources=["arxiv", "s2"], max_results=50,
                                client=make_client(full_handler))
    assert errors == {}
    # arXiv 2 篇 + S2 1 篇，其中 S2 标题与 arXiv 第一篇相同 → 去重后 2 篇
    assert len(papers) == 2
    assert papers[0].metadata["source"] == "arxiv"


def test_search_all_caps_results(test_settings):
    papers, _ = search_all("rag", test_settings, sources=["arxiv"], max_results=1,
                           client=make_client(full_handler))
    assert len(papers) == 1


def test_search_all_source_error_isolated(test_settings):
    def failing_s2(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.semanticscholar.org":
            return httpx.Response(500, text="boom")
        return full_handler(request)

    papers, errors = search_all("rag", test_settings, sources=["arxiv", "s2"],
                                client=make_client(failing_s2))
    assert len(papers) == 2  # arXiv 不受影响
    assert "semantic_scholar" in errors
    assert "HTTPStatusError" in errors["semantic_scholar"]


def test_store_paper_idempotent(db, test_settings: Settings):
    papers = arxiv_search("rag", test_settings, client=make_client(full_handler))
    pid1, new1 = store_paper(db, papers[0])
    pid2, new2 = store_paper(db, papers[0])
    assert new1 and not new2 and pid1 == pid2
    assert db.scalar("SELECT COUNT(*) FROM papers") == 1


def test_link_project_paper_idempotent(db):
    pid = db.insert(f"INSERT INTO projects (name, question) VALUES ({db.ph}, {db.ph})", ["t", "q"])
    paper_id = db.insert(
        f"INSERT INTO papers (title, authors) VALUES ({db.ph}, {db.ph})", ["T", "[]"]
    )
    assert link_project_paper(db, pid, paper_id, "q") is True
    assert link_project_paper(db, pid, paper_id, "q") is False
    assert db.scalar("SELECT COUNT(*) FROM projects_papers") == 1
