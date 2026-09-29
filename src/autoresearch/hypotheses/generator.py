"""假设生成器：矛盾消解 / 缺口填补 / 方法组合三类来源，LLM 主路 + 模板规则兜底。

每条候选假设必须具备：
- statement：可证伪的明确断言（含方向）
- rationale：图谱证据说明（含溯源 id）
- testability：{datasets, metrics, baseline, direction, ...} —— 有基线、有指标
- novelty：0-1 新颖度（规则路径按来源类型赋值，LLM 路径由模型评估）
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from itertools import combinations

from loguru import logger

from ..config import Settings, get_settings
from ..db import Database
from ..literature.extractor import _probe_llm
from ..graph.builder import _TERM_LOOKUP
from .ranker import rank

_LLM_SYSTEM = "你是资深科研人员，提出可验证、有基线、有指标的研究假设，只输出严格 JSON。"

# 每类候选送 LLM 改写的上限（其余保持规则模板版本）
_LLM_ENHANCE_LIMIT = 20

_CONTRADICTION_CAP = 60
_GAP_CAP = 80
_COMBINATION_PER_DATASET = 8
_COMBINATION_CAP = 60


def _dedupe_key(statement: str) -> str:
    norm = re.sub(r"\s+", " ", (statement or "").lower()).strip()
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()


def _match_terms(text: str) -> tuple[list[str], list[str], list[str]]:
    """在文本中匹配词典术语 → (methods, datasets, metrics)。"""
    ns = re.sub(r"\s+", " ", (text or "").lower())
    buckets: dict[str, list[str]] = {"method": [], "dataset": [], "metric": []}
    for norm, (disp, etype, rx) in _TERM_LOOKUP.items():
        if rx.search(ns):
            buckets[etype].append(disp)
    return buckets["method"], buckets["dataset"], buckets["metric"]


# ---------------- 图谱上下文 ----------------
def _top_datasets(db: Database, limit: int = 5) -> list[str]:
    rows = db.query(
        f"SELECT te.name AS name, COUNT(*) AS n FROM relations r "
        f"JOIN entities te ON te.id = r.target_entity_id "
        f"WHERE r.type = 'uses' GROUP BY te.name ORDER BY n DESC LIMIT {int(limit)}"
    )
    return [r["name"] for r in rows]


def _top_metrics(db: Database, limit: int = 5) -> list[str]:
    rows = db.query(
        f"SELECT te.name AS name, COUNT(*) AS n FROM relations r "
        f"JOIN entities te ON te.id = r.target_entity_id "
        f"WHERE r.type = 'measured_by' GROUP BY te.name ORDER BY n DESC LIMIT {int(limit)}"
    )
    return [r["name"] for r in rows]


def _method_context(db: Database, method: str) -> tuple[list[str], list[str]]:
    datasets = db.query(
        f"SELECT te.name AS name FROM relations r "
        f"JOIN entities se ON se.id = r.source_entity_id "
        f"JOIN entities te ON te.id = r.target_entity_id "
        f"WHERE r.type = 'uses' AND se.name = {db.ph} ORDER BY r.confidence DESC LIMIT 3",
        [method],
    )
    metrics = db.query(
        f"SELECT te.name AS name FROM relations r "
        f"JOIN entities se ON se.id = r.source_entity_id "
        f"JOIN entities te ON te.id = r.target_entity_id "
        f"WHERE r.type = 'measured_by' AND se.name = {db.ph} ORDER BY r.confidence DESC LIMIT 3",
        [method],
    )
    return [r["name"] for r in datasets], [r["name"] for r in metrics]


def _fill_testability(db: Database, cand: dict, global_ds: list[str], global_met: list[str]) -> dict:
    """确保 testability 三要素齐备（数据集/指标/基线）。"""
    t = cand.setdefault("testability", {})
    if not t.get("datasets"):
        mds, _ = _method_context(db, cand["testability"].get("method") or "")
        t["datasets"] = mds or global_ds[:2] or ["基准数据集"]
    if not t.get("metrics"):
        _, mmet = _method_context(db, cand["testability"].get("method") or "")
        t["metrics"] = mmet or global_met[:2] or ["主要指标"]
    if not t.get("baseline"):
        t["baseline"] = "强基线实现"
    return cand


# ---------------- 三类候选 ----------------
def _contradiction_candidates(db: Database) -> list[dict]:
    rows = db.query(
        f"SELECT r.id AS relation_id, r.confidence, r.evidence, "
        f"se.name AS finding_a, te.name AS finding_b "
        f"FROM relations r "
        f"JOIN entities se ON se.id = r.source_entity_id "
        f"JOIN entities te ON te.id = r.target_entity_id "
        f"WHERE r.type = 'contradicts' ORDER BY r.confidence DESC LIMIT {_CONTRADICTION_CAP}"
    )
    out: list[dict] = []
    for r in rows:
        quote = ((r.get("evidence") or [{}])[0]).get("quote") or ""
        match = re.match(r"POS\[(.+?)\]: (.*) \|\| NEG: (.*)", quote)
        if not match:
            continue
        method, pos_sent, neg_sent = match.group(1), match.group(2), match.group(3)
        pos_m, pos_d, pos_met = _match_terms(pos_sent)
        neg_m, neg_d, neg_met = _match_terms(neg_sent)
        datasets = list(dict.fromkeys(pos_d + neg_d))
        metrics = list(dict.fromkeys(pos_met + neg_met))
        others = [m for m in dict.fromkeys(pos_m + neg_m) if m.lower() != method.lower()]
        baseline = others[0] if others else None
        metric0 = metrics[0] if metrics else "主要指标"
        ds_label = "/".join(datasets[:2]) if datasets else "对应基准"
        out.append({
            "statement": (
                f"假设：在{ds_label}上以{metric0}评测时，{method}相对基线{baseline or '强基线实现'}"
                f"的表现差异主要源于实验条件（实现细节与数据划分）不一致；"
                f"统一实验协议后，{method}的{metric0}将稳定优于基线。"
            ),
            "rationale": (
                f"图谱发现关于{method}存在跨论文相反结论：「{pos_sent[:80]}」与「{neg_sent[:80]}」，"
                f"提示其效果依赖未被控制的实验条件，值得受控复现验证。"
            ),
            "testability": {"datasets": datasets, "metrics": metrics, "baseline": baseline,
                            "direction": "优于基线", "method": method,
                            "type": "contradiction_resolution"},
            "novelty": 0.6,
            "metadata": {"source": "contradiction", "relation_ids": [r["relation_id"]],
                         "entity_ids": [], "quotes": [pos_sent[:160], neg_sent[:160]]},
            "dedupe_key_semantic": f"contradiction|{method.lower()}|{ds_label}",
        })
    return out


def _gap_candidates(db: Database) -> list[dict]:
    rows = db.query(
        f"SELECT r.target_entity_id AS gap_id, e.name AS gap_name, "
        f"se.name AS method, r.id AS rel_id "
        f"FROM relations r "
        f"JOIN entities se ON se.id = r.source_entity_id "
        f"JOIN entities e ON e.id = r.target_entity_id "
        f"WHERE r.type = 'addresses' LIMIT {_GAP_CAP * 3}"
    )
    by_gap: dict[int, dict] = defaultdict(lambda: {"name": "", "methods": [], "rel_ids": []})
    for r in rows:
        g = by_gap[r["gap_id"]]
        g["name"] = r["gap_name"]
        if r["method"] not in g["methods"]:
            g["methods"].append(r["method"])
        g["rel_ids"].append(r["rel_id"])
    out: list[dict] = []
    for gap_id, g in list(by_gap.items())[:_GAP_CAP]:
        gap_short = re.sub(r"\s+", " ", g["name"])[:60]
        for method in g["methods"][:3]:
            out.append({
                "statement": (
                    f"假设：针对研究缺口「{gap_short}」，在对应基准上对{method}"
                    f"做针对性改进（检索/融合/训练策略层面）后，其主要指标可相对强基线提升至少 5%。"
                ),
                "rationale": (
                    f"图谱将「{gap_short}」标记为研究缺口，且{method}与其存在 addresses 关联，"
                    f"说明该方向尚未被充分解决且与现有方法直接相关。"
                ),
                "testability": {"datasets": [], "metrics": [], "baseline": "强基线实现",
                                "direction": "指标提升≥5%", "method": method,
                                "type": "gap_filling"},
                "novelty": 0.55,
                "metadata": {"source": "gap", "relation_ids": g["rel_ids"][:4],
                             "entity_ids": [gap_id], "quotes": [g["name"][:160]]},
                "dedupe_key_semantic": f"gap|{gap_id}|{method.lower()}",
            })
    return out


def _combination_candidates(db: Database) -> list[dict]:
    rows = db.query(
        f"SELECT se.name AS method, te.name AS dataset, r.id AS rel_id, r.confidence "
        f"FROM relations r "
        f"JOIN entities se ON se.id = r.source_entity_id "
        f"JOIN entities te ON te.id = r.target_entity_id "
        f"WHERE r.type = 'uses' ORDER BY r.confidence DESC"
    )
    by_ds: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_ds[r["dataset"]].append(r)
    out: list[dict] = []
    for dataset, items in by_ds.items():
        seen_methods: list[str] = []
        rel_of: dict[str, int] = {}
        for r in items:
            if r["method"] not in seen_methods:
                seen_methods.append(r["method"])
                rel_of[r["method"]] = r["rel_id"]
            if len(seen_methods) >= 8:
                break
        for m1, m2 in list(combinations(seen_methods, 2))[:_COMBINATION_PER_DATASET]:
            out.append({
                "statement": (
                    f"假设：在{dataset}上，将{m2}与{m1}级联组合（{m2}作用于{m1}的输出）后，"
                    f"主要指标可相对单独使用{m1}提升至少 3%。"
                ),
                "rationale": (
                    f"图谱中{m1}与{m2}均与{dataset}存在 uses 关联，二者作用于同一任务的不同环节，"
                    f"具备级联组合的可行性与互补空间。"
                ),
                "testability": {"datasets": [dataset], "metrics": [], "baseline": f"单独使用{m1}",
                                "direction": "指标提升≥3%", "method": m2,
                                "type": "method_combination"},
                "novelty": 0.65,
                "metadata": {"source": "combination", "relation_ids": [rel_of[m1], rel_of[m2]],
                             "entity_ids": [], "quotes": []},
                "dedupe_key_semantic": f"combination|{m1.lower()}|{m2.lower()}|{dataset.lower()}",
            })
    out = out[:_COMBINATION_CAP]
    return out


# ---------------- LLM 增强 ----------------
_LLM_ENHANCE_SYSTEM = "你是资深科研人员，提出可验证、有基线、有指标的研究假设，只输出严格 JSON。"

# 注意：模板含 JSON 花括号，不能用 str.format；用拼接传候选
_LLM_ENHANCE_HEAD = (
    "下面是依据知识图谱证据生成的候选研究假设。请把它改写为更精确、可证伪的表述，"
    "并评估新颖度。输出 JSON：\n"
    '{"statement": "...", "rationale": "...", "novelty": 0.0}\n'
    "要求：statement 必须指明在什么数据集上、用什么指标、相对什么基线、预期什么方向；"
    "不要编造图谱中不存在的实体。\n\n候选假设："
)


def _llm_enhance(llm, candidates: list[dict]) -> None:
    targets = candidates[:_LLM_ENHANCE_LIMIT]
    prompts = [
        _LLM_ENHANCE_HEAD + json.dumps(
            {"statement": c["statement"], "rationale": c["rationale"],
             "testability": c["testability"]}, ensure_ascii=False)
        for c in targets
    ]
    outs = llm.batch_complete(prompts, system=_LLM_SYSTEM)
    for cand, out in zip(targets, outs):
        try:
            match = re.search(r"\{.*\}", out or "", re.DOTALL)
            if not match:
                continue
            data = json.loads(match.group())
            if data.get("statement"):
                cand["statement"] = str(data["statement"])[:400]
            if data.get("rationale"):
                cand["rationale"] = str(data["rationale"])[:500]
            if data.get("novelty") is not None:
                cand["novelty"] = min(max(float(data["novelty"]), 0.0), 1.0)
        except (ValueError, TypeError, AttributeError) as exc:
            logger.warning("LLM 假设改写解析失败，保留规则版本: {}", exc)


# ---------------- 主流程 ----------------
def generate_hypotheses(db: Database, settings: Settings | None = None, *, project_id: int,
                        max_hypotheses: int = 50, use_llm: bool = True) -> dict:
    """从图谱生成假设并幂等入库，返回执行摘要。"""
    settings = settings or get_settings()
    started = time.perf_counter()
    has_chunks = db.scalar(
        f"SELECT COUNT(*) FROM chunks c JOIN projects_papers pp ON pp.paper_id = c.paper_id "
        f"WHERE pp.project_id = {db.ph}", [project_id],
    )
    if not has_chunks:
        raise ValueError("项目还没有文献 chunks：请先运行文献流水线与图谱构建")
    if not db.scalar("SELECT COUNT(*) FROM entities"):
        raise ValueError("图谱为空：请先运行 `autoresearch graph` 构建知识图谱")

    global_ds, global_met = _top_datasets(db), _top_metrics(db)
    candidates = _contradiction_candidates(db) + _gap_candidates(db) + _combination_candidates(db)
    if not candidates:
        raise ValueError("图谱中缺少矛盾/缺口/方法组合，无法生成假设")
    for c in candidates:
        _fill_testability(db, c, global_ds, global_met)

    llm = _probe_llm(settings) if (use_llm and settings.llm_enabled) else None
    llm_used = False
    if llm is not None:
        try:
            _llm_enhance(llm, candidates)
            llm_used = True
        except Exception as exc:
            logger.warning("LLM 假设增强失败（{}），全部使用规则模板", exc)
    kept = rank(candidates, top_n=max_hypotheses)
    stored = 0
    for c in kept:
        row_id = db.insert_ignore(
            f"INTO hypotheses (project_id, statement, rationale, testability, novelty, "
            f"status, metadata, dedupe_key) "
            f"VALUES ({db.ph}, {db.ph}, {db.ph}, {db.ph}, {db.ph}, {db.ph}, {db.ph}, {db.ph})",
            [project_id, c["statement"], c["rationale"], db.dumps(c["testability"]),
             c["novelty"], "proposed", db.dumps(c["metadata"]), _dedupe_key(c["statement"])],
            conflict_cols="dedupe_key",
        )
        stored += int(row_id is not None)

    by_source = dict(Counter((c.get("metadata") or {}).get("source", "?") for c in kept))
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info("假设生成完成 project#{}: 候选 {} / 保留 {} / 新入库 {} / {:.1f}s",
                project_id, len(candidates), len(kept), stored, elapsed_ms / 1000)
    return {
        "project_id": project_id,
        "candidates": len(candidates),
        "generated": len(kept),
        "stored": stored,
        "by_source": by_source,
        "llm_used": llm_used,
        "elapsed_ms": elapsed_ms,
    }
