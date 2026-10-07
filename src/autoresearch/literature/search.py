"""文献检索：arXiv / Semantic Scholar / PubMed 三源，统一 Paper 输出 + 标题去重。

所有函数接受可选的 httpx.Client（测试注入 MockTransport），未提供时自建并负责关闭。
"""

from __future__ import annotations

import hashlib
import re
import time
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from typing import Iterator

import httpx
from loguru import logger

from ..config import Settings
from ..models import Paper

# arXiv 的反爬过滤会 406 拒绝 python-httpx 默认 UA 及部分非常规 UA，
# 需使用浏览器兼容 UA（实测 2026-09-19）
_USER_AGENT = "Mozilla/5.0 (compatible; AutoResearch/0.2; research tool)"
_ATOM = "http://www.w3.org/2005/Atom"


def dedupe_key(title: str, year: int | None = None) -> str:
    """标题归一化（小写 + 空白折叠）+ 年份 → sha1。"""
    norm = re.sub(r"\s+", " ", (title or "").strip().lower())
    return hashlib.sha1(f"{norm}|{year or ''}".encode("utf-8")).hexdigest()


@contextmanager
def _own(settings: Settings, client: httpx.Client | None) -> Iterator[httpx.Client]:
    """使用注入的 client，或自建一个（并负责关闭）。"""
    if client is not None:
        yield client
    else:
        with httpx.Client(
            timeout=settings.http_timeout,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        ) as c:
            yield c


def _get_with_retry(
    client: httpx.Client, url: str, *, attempts: int = 3, **kwargs
) -> httpx.Response:
    """GET + 退避重试：429/406（限流与反爬惩罚，S2 未认证常态）及 5xx、网络抖动可重试。

    arXiv 实测会对突发请求按 IP 返回 406 并冷却一段时间，故退避需足够长（10s/30s）。
    """
    last: Exception | None = None
    for i in range(attempts):
        try:
            resp = client.get(url, **kwargs)
            if resp.status_code in (429, 406) or resp.status_code >= 500:
                last = httpx.HTTPStatusError(
                    f"HTTP {resp.status_code}", request=resp.request, response=resp
                )
                if i < attempts - 1:
                    time.sleep((i + 1) * 10.0)
                continue
            return resp
        except httpx.TransportError as exc:
            last = exc
            if i < attempts - 1:
                time.sleep((i + 1) * 10.0)
    assert last is not None
    raise last


def _urllib_get_with_retry(url: str, timeout: float, attempts: int = 3) -> str:
    """标准库 urllib GET + 退避重试（arXiv 专用，见 arxiv_search 说明）。"""
    import urllib.error
    import urllib.request

    last: Exception | None = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (429, 406) or exc.code >= 500:
                if i < attempts - 1:
                    time.sleep((i + 1) * 10.0)
                continue
            raise
        except OSError as exc:  # URLError/网络抖动
            last = exc
            if i < attempts - 1:
                time.sleep((i + 1) * 10.0)
    assert last is not None
    raise last


# ---------- arXiv ----------
def _parse_arxiv_xml(xml_text: str) -> list[Paper]:
    root = ET.fromstring(xml_text)
    papers: list[Paper] = []
    for entry in root.findall(f"{{{_ATOM}}}entry"):

        def tag_text(tag: str, elem=entry) -> str:
            node = elem.find(f"{{{_ATOM}}}{tag}")
            return (node.text or "").strip() if node is not None else ""

        title = re.sub(r"\s+", " ", tag_text("title"))
        abstract = re.sub(r"\s+", " ", tag_text("summary"))
        authors = [
            a.findtext(f"{{{_ATOM}}}name", "").strip() for a in entry.findall(f"{{{_ATOM}}}author")
        ]
        published = tag_text("published")
        year = int(published[:4]) if published[:4].isdigit() else None
        url = tag_text("id")
        pdf_url = ""
        for link in entry.findall(f"{{{_ATOM}}}link"):
            if link.get("type") == "application/pdf":
                pdf_url = link.get("href") or ""
                break
        arxiv_id = url.rsplit("/abs/", 1)[-1] if url else ""
        papers.append(
            Paper(
                id=0,
                title=title,
                authors=[a for a in authors if a],
                year=year,
                venue="arXiv",
                abstract=abstract or None,
                url=url or None,
                dedupe_key=dedupe_key(title, year),
                metadata={"source": "arxiv", "arxiv_id": arxiv_id, "pdf_url": pdf_url},
            )
        )
    return papers


def arxiv_search(
    query: str, settings: Settings, client: httpx.Client | None = None, max_results: int = 50
) -> list[Paper]:
    """arXiv 检索。

    传输层说明（实测 2026-09-19）：arXiv 的 WAF 会按客户端指纹拦截——httpx 发起的
    多词/短语查询一律 406，而标准库 urllib 同参数放行。因此真实流量走 urllib；
    注入 client（测试 MockTransport）时走 httpx 以保持可测试性。
    """
    from urllib.parse import quote

    search_query = f'all:"{query}"'
    url = (
        f"{settings.arxiv_api}?search_query={quote(search_query)}"
        f"&start=0&max_results={max_results}&sortBy=relevance"
    )
    if client is not None:
        resp = _get_with_retry(client, url)
        resp.raise_for_status()
        xml_text = resp.text
    else:
        xml_text = _urllib_get_with_retry(url, settings.http_timeout)
    papers = _parse_arxiv_xml(xml_text)
    logger.info("arXiv 检索 {}: {} 篇", query, len(papers))
    return papers


# ---------- Semantic Scholar ----------
def semantic_scholar_search(
    query: str, settings: Settings, client: httpx.Client | None = None, max_results: int = 50
) -> list[Paper]:
    with _own(settings, client) as c:
        headers = (
            {"x-api-key": settings.semantic_scholar_key} if settings.semantic_scholar_key else {}
        )
        resp = _get_with_retry(
            c,
            f"{settings.semantic_scholar_api.rstrip('/')}/paper/search",
            params={
                "query": query,
                "limit": min(max_results, 100),
                "fields": "title,authors,year,venue,abstract,externalIds,url",
            },
            headers=headers,
        )
        resp.raise_for_status()
        papers: list[Paper] = []
        for item in resp.json().get("data") or []:
            title = (item.get("title") or "").strip()
            if not title:
                continue
            ext = item.get("externalIds") or {}
            papers.append(
                Paper(
                    id=0,
                    title=re.sub(r"\s+", " ", title),
                    authors=[a.get("name", "") for a in item.get("authors") or []],
                    year=item.get("year"),
                    venue=item.get("venue") or None,
                    abstract=item.get("abstract"),
                    url=item.get("url"),
                    dedupe_key=dedupe_key(title, item.get("year")),
                    metadata={
                        "source": "semantic_scholar",
                        "s2_id": item.get("paperId"),
                        "doi": ext.get("DOI"),
                        "arxiv_id": ext.get("ArXiv"),
                    },
                )
            )
        logger.info("Semantic Scholar 检索 {}: {} 篇", query, len(papers))
        return papers


# ---------- PubMed ----------
def _parse_pubmed_abstracts(xml_text: str) -> dict[str, str | None]:
    root = ET.fromstring(xml_text)
    out: dict[str, str | None] = {}
    for article in root.iter("PubmedArticle"):
        pmid = article.findtext(".//MedlineCitation/PMID") or ""
        parts = [(el.text or "").strip() for el in article.findall(".//Abstract/AbstractText")]
        text = re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip()
        if pmid:
            out[pmid] = text or None
    return out


def pubmed_search(
    query: str, settings: Settings, client: httpx.Client | None = None, max_results: int = 50
) -> list[Paper]:
    base = settings.pubmed_api.rstrip("/")
    with _own(settings, client) as c:
        r1 = _get_with_retry(
            c,
            f"{base}/esearch.fcgi",
            params={
                "db": "pubmed",
                "term": query,
                "retmax": max_results,
                "retmode": "json",
                "sort": "relevance",
            },
        )
        r1.raise_for_status()
        ids = (r1.json().get("esearchresult") or {}).get("idlist") or []
        if not ids:
            return []

        r2 = _get_with_retry(
            c,
            f"{base}/esummary.fcgi",
            params={
                "db": "pubmed",
                "id": ",".join(ids),
                "retmode": "json",
            },
        )
        r2.raise_for_status()
        summary = r2.json().get("result") or {}

        r3 = _get_with_retry(
            c,
            f"{base}/efetch.fcgi",
            params={
                "db": "pubmed",
                "id": ",".join(ids),
                "retmode": "xml",
            },
        )
        r3.raise_for_status()
        abstracts = _parse_pubmed_abstracts(r3.text)

        papers: list[Paper] = []
        for pmid in ids:
            item = summary.get(pmid) or {}
            title = re.sub(r"\s+", " ", item.get("title") or "").strip()
            if not title:
                continue
            authors = [a.get("name", "") for a in item.get("authors") or []]
            match = re.search(r"\d{4}", item.get("pubdate") or "")
            year = int(match.group()) if match else None
            doi = ""
            for ai in item.get("articleids") or []:
                if ai.get("idtype") == "doi":
                    doi = ai.get("value") or ""
            papers.append(
                Paper(
                    id=0,
                    title=title,
                    authors=authors,
                    year=year,
                    venue=item.get("source") or None,
                    abstract=abstracts.get(pmid),
                    url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    dedupe_key=dedupe_key(title, year),
                    metadata={"source": "pubmed", "pmid": pmid, "doi": doi},
                )
            )
        logger.info("PubMed 检索 {}: {} 篇", query, len(papers))
        return papers


# ---------- 多源聚合 ----------
_SOURCES = {
    "arxiv": arxiv_search,
    "semantic_scholar": semantic_scholar_search,
    "pubmed": pubmed_search,
}
SOURCE_ALIASES = {
    "arxiv": "arxiv",
    "s2": "semantic_scholar",
    "semantic_scholar": "semantic_scholar",
    "pubmed": "pubmed",
}


def search_all(
    query: str,
    settings: Settings,
    sources: list[str] | tuple[str, ...] = ("arxiv",),
    max_results: int = 50,
    client: httpx.Client | None = None,
) -> tuple[list[Paper], dict]:
    """多源检索 + 跨源去重，返回 (papers, errors)。单源失败不影响其他源。"""
    papers: list[Paper] = []
    seen: set[str] = set()
    errors: dict[str, str] = {}
    with _own(settings, client) as c:
        for raw in sources:
            name = SOURCE_ALIASES.get(raw.strip().lower())
            if name is None:
                errors[raw] = f"未知来源，可选：{sorted(SOURCE_ALIASES)}"
                continue
            try:
                # arXiv 在共享 client 存在时也注入之（测试 MockTransport 场景）；
                # 真实流量下 shared client 仅用于 S2/PubMed，arXiv 走 urllib（见 arxiv_search）
                source_client = client if name == "arxiv" else c
                found = _SOURCES[name](
                    query, settings, client=source_client, max_results=max_results
                )
            except Exception as exc:
                errors[name] = f"{type(exc).__name__}: {exc}"
                logger.warning("检索 {} 失败: {}", name, exc)
                continue
            for p in found:
                if p.dedupe_key in seen:
                    continue
                seen.add(p.dedupe_key)
                papers.append(p)
    return papers[:max_results], errors
