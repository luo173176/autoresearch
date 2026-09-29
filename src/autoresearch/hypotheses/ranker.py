"""假设排序与去重：novelty × 可验证性 × 证据支持度加权，token Jaccard 相似去重。"""
from __future__ import annotations

import re


def _tokens(statement: str) -> set[str]:
    return set(re.findall(r"[a-z0-9\u4e00-\u9fff]+", (statement or "").lower()))


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def score_candidate(c: dict) -> float:
    """score = 0.5*novelty + 0.3*可验证性完整度 + 0.2*证据支持度。"""
    t = c.get("testability") or {}
    testability = (
        0.4
        + 0.2 * bool(t.get("datasets"))
        + 0.2 * bool(t.get("metrics"))
        + 0.2 * bool(t.get("baseline"))
    )
    meta = c.get("metadata") or {}
    support = min(len(meta.get("quotes") or []) / 3.0, 1.0)
    return 0.5 * float(c.get("novelty") or 0.5) + 0.3 * testability + 0.2 * support


def rank(candidates: list[dict], top_n: int = 50, similarity: float = 0.95) -> list[dict]:
    """两级去重后按得分排序取 top_n。

    1) 语义键去重（dedupe_key_semantic = 来源+实体组合）：同一方法对的矛盾、
       同一缺口、同一方法组合只保留得分最高的一条——模板句共享骨架词，
       文本相似度会误杀不同实体的假设；
    2) 文本 Jaccard（默认 0.95）兜底近似重复。
    """
    scored = sorted(candidates, key=score_candidate, reverse=True)
    kept: list[dict] = []
    seen_tokens: list[set[str]] = []
    seen_keys: set[str] = set()
    for c in scored:
        key = c.get("dedupe_key_semantic")
        if key:
            if key in seen_keys:
                continue
            seen_keys.add(key)
        tokens = _tokens(c.get("statement"))
        if any(jaccard(tokens, prev) >= similarity for prev in seen_tokens):
            continue
        seen_tokens.append(tokens)
        kept.append(c)
        if len(kept) >= top_n:
            break
    return kept
