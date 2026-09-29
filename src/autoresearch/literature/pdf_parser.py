"""PDF 解析与下载：pymupdf 主力；GROBID 可选（settings.grobid_url，后续接入）。"""
from __future__ import annotations

from pathlib import Path

import httpx
from loguru import logger

from ..config import Settings

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    try:
        import fitz  # 老版本 pymupdf 的兼容导入名
    except ImportError:
        fitz = None  # type: ignore[assignment]

_UA = "AutoResearch/0.1 (research tool)"


class PdfParseError(RuntimeError):
    pass


def download_pdf(url: str, dest: Path | str, settings: Settings,
                 client: httpx.Client | None = None) -> Path:
    """下载 PDF 到 dest；内容不是 PDF（无 %PDF 魔数）时抛 PdfParseError。"""
    dest = Path(dest)
    if client is not None:
        resp = client.get(url)
        resp.raise_for_status()
        content = resp.content
    else:
        with httpx.Client(timeout=settings.http_timeout, follow_redirects=True,
                          headers={"User-Agent": _UA}) as c:
            resp = c.get(url)
            resp.raise_for_status()
            content = resp.content
    if not content[:5].startswith(b"%PDF"):
        raise PdfParseError(f"响应不是 PDF（{url}）")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    logger.info("已下载 PDF {} -> {}", url, dest)
    return dest


def parse_pdf(path: Path | str) -> dict:
    """解析 PDF → {title, text, n_pages, metadata}；失败抛 PdfParseError。"""
    if fitz is None:
        raise PdfParseError("未安装 pymupdf：pip install pymupdf")
    path = Path(path)
    try:
        doc = fitz.open(path)
    except Exception as exc:
        raise PdfParseError(f"无法打开 {path}: {exc}") from exc
    try:
        if doc.needs_pass:
            raise PdfParseError(f"PDF 已加密: {path}")
        pages = [page.get_text("text") for page in doc]
        meta = dict(doc.metadata or {})
    finally:
        doc.close()

    text = "\n".join(pages).strip()
    if not text:
        raise PdfParseError(f"PDF 无可抽取文本（可能为扫描件）: {path}")

    title = (meta.get("title") or "").strip()
    if not title:  # 元数据缺标题时取正文第一个非空行
        for line in text.splitlines():
            line = line.strip()
            if line:
                title = line[:200]
                break
    return {"title": title, "text": text, "n_pages": len(pages), "metadata": meta}
