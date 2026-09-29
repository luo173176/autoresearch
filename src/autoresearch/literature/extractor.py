"""分块与元数据抽取：LLM 增强（可选、缓存、断点续跑）+ 无 LLM 时启发式兜底。

设计（DECISIONS.md D-013）：
- 先用 4s 超时探测 LLM 服务（GET /models）；不可达 → 全部走启发式，离线可跑、测试确定性
- LLM 批量抽取走 LLMClient（缓存 key 含 prompt_version），失败整体回退启发式
"""
from __future__ import annotations

import re
from collections import Counter

import httpx
from loguru import logger

from ..config import Settings, get_settings
from ..db import Database
from ..llm.client import LLMClient

_STOPWORDS = frozenset(
    "a an and are as at be been by for from has have in into is it its of on or "
    "that the to with this these those we our you your using based approach "
    "methods results paper study propose proposed show shows can may which".split()
)


def chunk_text(text: str, max_chars: int = 1200, overlap: int = 150) -> list[str]:
    """按段落聚合分块；超长段落滑窗硬切（带 overlap）。"""
    if not text or not text.strip():
        return []
    paras = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paras:
        while len(para) > max_chars:
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(para[:max_chars])
            para = para[max(0, max_chars - overlap):]
        if not buf:
            buf = para
        elif len(buf) + len(para) + 2 <= max_chars:
            buf += "\n" + para
        else:
            chunks.append(buf)
            buf = para
    if buf:
        chunks.append(buf)
    return chunks


def heuristic_summary(text: str, max_chars: int = 280) -> str:
    """无 LLM 兜底：按句子拼接至 max_chars。"""
    sentences = re.split(r"(?<=[.!?。])\s+", text.strip())
    out = ""
    for s in sentences:
        if not s:
            continue
        if len(out) + len(s) + 1 > max_chars:
            break
        out = f"{out} {s}".strip()
    return out or text[:max_chars]


def heuristic_keywords(text: str, top_k: int = 8) -> list[str]:
    """无 LLM 兜底：去停用词后按词频取 top_k。"""
    words = re.findall(r"[A-Za-z][A-Za-z\-]{2,}", text.lower())
    words = [w for w in words if w not in _STOPWORDS]
    return [w for w, _ in Counter(words).most_common(top_k)]


# 探测结果按 LLM 端点记忆：流水线逐论文调用 build_chunks 时只探测一次
_PROBE_CACHE: dict[str, "LLMClient | None"] = {}


def reset_llm_probe_cache() -> None:
    """清空探测缓存（设置页改完 LLM 配置后调用，下一次流水线重新探测）。"""
    _PROBE_CACHE.clear()


def _probe_llm(settings: Settings) -> LLMClient | None:
    """快速探测 LLM 服务是否可达（4s，无重试）；不可达返回 None（结果按端点缓存）。"""
    if not settings.llm_enabled:
        return None
    base = settings.llm_base_url.rstrip("/")
    if base in _PROBE_CACHE:
        return _PROBE_CACHE[base]
    try:
        resp = httpx.get(f"{base}/models", timeout=4.0)
        resp.raise_for_status()
        client: LLMClient | None = LLMClient(settings)
    except Exception as exc:
        logger.warning("LLM 服务不可达（{}），抽取降级为启发式", exc)
        client = None
    _PROBE_CACHE[base] = client
    return client


_ENRICH_SYSTEM = "你是学术论文分析助手，输出严格遵循用户要求的格式。"


def _enrich_texts(llm: LLMClient, texts: list[str]) -> list[tuple[str, list[str]]] | None:
    """LLM 批量抽取 (summary, keywords)；结果不完整时返回 None 触发整体回退。"""
    prompts = [
        "对下面的学术文本片段，严格输出两行：\n"
        "第一行：一句中文摘要（不超过60字）\n"
        "第二行：英文关键词，逗号分隔，最多8个\n\n"
        f"文本：{t[:3000]}"
        for t in texts
    ]
    try:
        outs = llm.batch_complete(prompts, system=_ENRICH_SYSTEM)
    except Exception as exc:
        logger.warning("LLM 批量抽取失败（{}），回退启发式", exc)
        return None
    results: list[tuple[str, list[str]]] = []
    for out in outs:
        lines = [line.strip() for line in (out or "").splitlines() if line.strip()]
        summary = lines[0] if lines else ""
        keywords: list[str] = []
        if len(lines) > 1:
            keywords = [k.strip() for k in lines[1].replace("，", ",").split(",") if k.strip()][:8]
        if not summary:
            return None
        results.append((summary, keywords))
    return results


def build_chunks(db: Database, settings: Settings | None, paper_id: int, texts: list[str],
                 use_llm: bool = True) -> int:
    """为论文写入 chunks（幂等：已有 chunk 的论文跳过）。返回创建数量。"""
    settings = settings or get_settings()
    if not texts:
        return 0
    existing = db.scalar(f"SELECT COUNT(*) FROM chunks WHERE paper_id = {db.ph}", [paper_id])
    if existing:
        return 0

    rows = [(heuristic_summary(t), heuristic_keywords(t)) for t in texts]
    llm_used = False
    if use_llm and settings.llm_enabled:
        llm = _probe_llm(settings)
        if llm is not None:
            enriched = _enrich_texts(llm, texts)
            if enriched:
                rows = enriched
                llm_used = True

    n = 0
    for i, (text, (summary, keywords)) in enumerate(zip(texts, rows)):
        db.insert(
            f"INSERT INTO chunks (paper_id, text, summary, keywords, metadata) "
            f"VALUES ({db.ph}, {db.ph}, {db.ph}, {db.ph}, {db.ph})",
            [paper_id, text, summary, db.dumps(keywords),
             db.dumps({"position": i, "enriched": llm_used})],
        )
        n += 1
    return n
