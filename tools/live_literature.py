"""在线验收（需外网）：真实调用文献 API 检索并入库，打印流水线摘要与库内统计。

用法:
    python tools/live_literature.py [query] [max] [sources] [--download-pdfs]
例:
    python tools/live_literature.py "retrieval augmented generation" 50 arxiv,s2,pubmed --download-pdfs
"""
import json
import os
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
os.chdir(REPO)
os.environ.setdefault("AUTORESEARCH_SQLITE_PATH", str(REPO / "data" / "autoresearch.db"))
os.environ.setdefault("AUTORESEARCH_DATA_DIR", str(REPO / "data"))
os.environ.setdefault("AUTORESEARCH_LLM_CACHE_DIR", str(REPO / "data" / "cache" / "llm"))

from autoresearch.cli import main as cli_main  # noqa: E402
from autoresearch.config import get_settings  # noqa: E402
from autoresearch.db import Database  # noqa: E402


def main() -> int:
    query = sys.argv[1] if len(sys.argv) > 1 else "retrieval augmented generation"
    max_results = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    sources = sys.argv[3] if len(sys.argv) > 3 else "arxiv"
    extra = ["--download-pdfs"] if "--download-pdfs" in sys.argv else []

    code = cli_main([
        "literature", query, "--max", str(max_results), "--sources", sources, *extra,
    ])

    db = Database(get_settings())
    papers = db.query("SELECT title, abstract, pdf_path, metadata, year FROM papers LIMIT 1000")
    chunk_count = db.scalar("SELECT COUNT(*) FROM chunks")
    sources_counter = Counter((p.get("metadata") or {}).get("source", "unknown") for p in papers)
    with_text = sum(1 for p in papers if p.get("abstract") or p.get("pdf_path"))
    n = len(papers)
    print("=" * 60)
    print(f"[验收] 库内论文: {n} 篇 | chunks: {chunk_count}")
    print(f"[验收] 来源分布: {dict(sources_counter)}")
    print(f"[验收] 可用文本率(abstract或pdf): {with_text}/{n} = {with_text / n * 100:.0f}%" if n else "[验收] 无论文")
    for row in db.query(
        "SELECT p.title, c.summary, c.keywords FROM chunks c JOIN papers p ON p.id = c.paper_id LIMIT 3"
    ):
        print(f"[验收] 示例: {row['title'][:50]} | 摘要: {(row['summary'] or '')[:60]} | 关键词: {row['keywords']}")
    return code


if __name__ == "__main__":
    sys.exit(main())
