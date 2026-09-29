"""知识图谱构建：从 chunks 抽取六类实体与五类关系，带证据与置信度。

实体类型：method(方法) / dataset(数据集) / metric(指标) / finding(结论) / gap(研究缺口)
关系类型：uses(方法→数据集) / measured_by(方法→指标) / reports(结论→方法) /
          addresses(方法→缺口) / contradicts(结论↔结论，跨论文矛盾)
          另有 related_to 作通用兜底。

双路抽取（D-017）：
- LLM 路径：JSON 结构化抽取（走 LLMClient，缓存断点续跑），失败自动回退
- 规则路径（无 LLM 兜底）：内置方法/数据集/指标词典匹配 + 句级极性分析 +
  跨论文矛盾配对 + 词典覆盖不了的研究缺口句式
"""
from __future__ import annotations

import json
import re
import time
from collections import defaultdict

from loguru import logger

from ..config import Settings, get_settings
from ..db import Database
from ..literature.extractor import _probe_llm

# ---------------- 词典（规则路径的实体识别底座） ----------------
_LEXICON_RAW: dict[str, tuple[str, ...]] = {
    "method": (
        "retrieval augmented generation", "dense retrieval", "sparse retrieval", "BM25",
        "dense passage retrieval", "DPR", "cross-encoder", "bi-encoder", "ColBERT",
        "re-ranking", "reranking", "query expansion", "query rewriting", "hybrid retrieval",
        "fine-tuning", "parameter efficient fine tuning", "LoRA", "QLoRA", "adapter",
        "prefix tuning", "prompt tuning", "prompt engineering", "in-context learning",
        "few-shot learning", "zero-shot learning", "chain-of-thought", "instruction tuning",
        "RLHF", "PPO", "DPO", "reinforcement learning", "self-supervised learning",
        "contrastive learning", "knowledge distillation", "quantization", "pruning",
        "mixture of experts", "transformer", "attention", "self-attention",
        "flash attention", "BERT", "RoBERTa", "T5", "BART", "LLaMA", "sentence-BERT",
        "ANN search", "FAISS", "HNSW", "product quantization", "graph neural network",
        "vector database", "semantic search", "masked language modeling",
        "multi-task learning", "curriculum learning", "data augmentation",
        "active learning", "self-consistency", "speculative decoding", "beam search",
        "late chunking", "contextual retrieval", "graph RAG", "agentic RAG",
    ),
    "dataset": (
        "natural questions", "TriviaQA", "MS MARCO", "HotpotQA", "SQuAD", "SQuAD 2.0",
        "FEVER", "KILT", "MMLU", "GSM8K", "HumanEval", "WikiText", "C4", "OpenBookQA",
        "BoolQ", "PubMedQA", "BioASQ", "COCO", "ImageNet", "GLUE", "SuperGLUE",
        "AG News", "MNLI", "SNLI", "2WikiMultihopQA", "MuSiQue", "AmbigQA", "BEIR",
        "SciQ", "CommonsenseQA", "HellaSwag", "TruthfulQA", "LongBench", "NarrativeQA",
        "Quoref", "WikiHop", "IMDB",
    ),
    "metric": (
        "accuracy", "exact match", "F1", "BLEU", "ROUGE", "ROUGE-L", "METEOR",
        "BERTScore", "nDCG", "MRR", "recall@k", "precision@k", "hit rate",
        "perplexity", "pass@k", "AUC", "AUROC", "top-1 accuracy", "top-5 accuracy",
        "hallucination rate", "faithfulness", "answer relevancy", "edit distance",
    ),
}

_POS_CUES = ("improv", "outperform", "boost", "exceed", "enhanc", "surpass",
             "superior", "state of the art", "sota")
_NEG_CUES = ("degrad", "hurt", "worse", "underperform", "fail", "hallucinat",
             "unreliable", "suffer", "lag behind", "mislead", "incorrect", "brittle")
_GAP_CUES = ("future work", "future research", "remains unexplored", "remains unclear",
             "remains challenging", "remains an open", "open problem", "open question",
             "open challenge", "lack of", "lacks", "limited research", "little attention",
             "underexplored", "under-studied", "bottleneck", "further investigation",
             "more research is needed", "scarce")

# PDF 解析噪声（表格/代码/邮箱/引用条目/项目符号）会伪装成句子，需过滤后才能成为 finding/gap
_GARBAGE_MARKS = ("http://", "https://", "@", "=", "{", "}", "|", ">>", "```",
                  "def ", "import ", "://", "•", "·", "et al")
_BAD_PREFIXES = ("table ", "figure ", "fig ", "available at", "doi:", "arxiv:", "isbn",
                 "proceedings", "conference on", "journal of")
_REF_PATTERN = re.compile(r"^[A-Z][a-z]+,\s+[\"'“”‘’]?[A-Z]")  # "Li, “X..." 参考文献条目样式


def _looks_like_sentence(s: str) -> bool:
    """启发式句子质量过滤：长度、词数、无代码/URL/引用条目特征。"""
    if not (40 <= len(s) <= 300):
        return False
    if any(mark in s for mark in _GARBAGE_MARKS):
        return False
    low = _normalize(s[:24])
    if any(low.startswith(p) for p in _BAD_PREFIXES):
        return False
    if _REF_PATTERN.match(s.strip()):
        return False
    return len(s.split()) >= 6

ENTITY_TYPES = frozenset({"method", "dataset", "metric", "finding", "gap"})
RELATION_TYPES = frozenset({"uses", "measured_by", "reports", "contradicts", "addresses", "related_to"})


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("-", " ").replace("–", " ").lower()).strip()


def _build_lookup() -> dict[str, tuple[str, str, re.Pattern]]:
    lookup: dict[str, tuple[str, str, re.Pattern]] = {}
    for etype, names in _LEXICON_RAW.items():
        for name in names:
            norm = _normalize(name)
            lookup[norm] = (name, etype, re.compile(rf"(?<![a-z0-9]){re.escape(norm)}(?:s|es)?(?![a-z0-9])"))
    return lookup


_TERM_LOOKUP = _build_lookup()


def _polarity(norm_sentence: str) -> str | None:
    pos = any(c in norm_sentence for c in _POS_CUES)
    neg = any(c in norm_sentence for c in _NEG_CUES)
    if pos and neg:
        return None  # 正负混合，不作为结论/矛盾依据
    return "pos" if pos else ("neg" if neg else None)


# ---------------- 规则抽取 ----------------
def _extract_rules(text: str) -> dict:
    """规则抽取：返回 {"entities": [...], "relations": [...], "findings": [...]}。"""
    flat = re.sub(r"\s+", " ", text or "")
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", flat) if len(s.strip()) >= 12]
    entities: list[dict] = []
    relations: list[dict] = []
    findings: list[dict] = []

    seen_pairs: dict[tuple, dict] = {}
    chunk_methods: set[str] = set()
    chunk_datasets: set[str] = set()
    chunk_metrics: set[str] = set()

    def note_pair(src, stype, dst, dtype, rtype, conf, quote):
        key = (src, stype, dst, dtype, rtype)
        cur = seen_pairs.get(key)
        if cur is None or conf > cur["conf"]:
            seen_pairs[key] = {"conf": conf, "quote": quote}

    for sent in sentences:
        clean = sent.strip()
        ns = _normalize(clean)
        matched = [(disp, etype) for norm, (disp, etype, rx) in _TERM_LOOKUP.items() if rx.search(ns)]
        methods = [d for d, t in matched if t == "method"]
        datasets = [d for d, t in matched if t == "dataset"]
        metrics = [d for d, t in matched if t == "metric"]
        chunk_methods.update(methods)
        chunk_datasets.update(datasets)
        chunk_metrics.update(metrics)

        for m in methods:
            for d in datasets:
                note_pair(m, "method", d, "dataset", "uses", 0.6, clean[:200])
            for met in metrics:
                note_pair(m, "method", met, "metric", "measured_by", 0.6, clean[:200])

        pol = _polarity(ns)
        if pol and methods and _looks_like_sentence(clean):
            name = clean[:160]
            entities.append({"name": name, "type": "finding", "quote": clean[:200],
                             "meta": {"polarity": pol, "source": "rules"}})
            findings.append({"name": name, "methods": methods, "polarity": pol})
            for m in methods:
                relations.append({"source": name, "source_type": "finding", "target": m,
                                  "target_type": "method", "type": "reports",
                                  "quote": clean[:200], "confidence": 0.7})

        if any(c in ns for c in _GAP_CUES) and _looks_like_sentence(clean):
            name = clean[:160]
            entities.append({"name": name, "type": "gap", "quote": clean[:200],
                             "meta": {"source": "rules"}})
            for m in methods:
                relations.append({"source": m, "source_type": "method", "target": name,
                                  "target_type": "gap", "type": "addresses",
                                  "quote": clean[:200], "confidence": 0.5})

    # 发出句级关系（0.6），再补 chunk 级弱共现（句级未覆盖的配对，0.3）
    for (src, stype, dst, dtype, rtype), info in seen_pairs.items():
        relations.append({"source": src, "source_type": stype, "target": dst,
                          "target_type": dtype, "type": rtype,
                          "quote": info["quote"], "confidence": info["conf"]})
    for m in chunk_methods:
        for d in chunk_datasets:
            if (m, "method", d, "dataset", "uses") not in seen_pairs:
                relations.append({"source": m, "source_type": "method", "target": d,
                                  "target_type": "dataset", "type": "uses",
                                  "quote": flat[:160], "confidence": 0.3})
        for met in chunk_metrics:
            if (m, "method", met, "metric", "measured_by") not in seen_pairs:
                relations.append({"source": m, "source_type": "method", "target": met,
                                  "target_type": "metric", "type": "measured_by",
                                  "quote": flat[:160], "confidence": 0.3})

    for name, etype in {(d, t) for d, t in
                        [(d, "method") for d in chunk_methods]
                        + [(d, "dataset") for d in chunk_datasets]
                        + [(m, "metric") for m in chunk_metrics]}:
        entities.append({"name": name, "type": etype, "quote": flat[:200],
                         "meta": {"source": "lexicon"}})

    return {"entities": entities, "relations": relations, "findings": findings}


# ---------------- LLM 抽取 ----------------
_LLM_SYSTEM = "你是科研知识图谱构建专家，只输出严格 JSON，不要任何解释或代码块标记。"

# 注意：模板含 JSON 花括号，不能用 str.format；用拼接传文本
_LLM_PROMPT_HEAD = (
    "从下面的学术文本片段抽取实体与关系，输出 JSON（不要 markdown 代码块）：\n"
    '{"entities": [{"name": "实体名", "type": "method|dataset|metric|finding|gap", "quote": "原文片段"}],\n'
    ' "relations": [{"source": "源实体名", "source_type": "...", "target": "目标实体名", '
    '"target_type": "...", "type": "uses|measured_by|reports|contradicts|addresses", '
    '"quote": "原文依据", "confidence": 0.0}]}\n'
    "说明：method=方法/模型/技术，dataset=数据集/基准，metric=评价指标，"
    "finding=文中给出的具体结论（用原句），gap=研究缺口/未来方向；"
    "confidence 0-1 表示关系成立把握。没有内容就输出空数组。"
)


def _parse_llm_json(out: str) -> dict | None:
    if not out:
        return None
    match = re.search(r"\{.*\}", out, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group())
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    entities = []
    for e in data.get("entities") or []:
        if isinstance(e, dict) and e.get("name") and e.get("type") in ENTITY_TYPES:
            entities.append({"name": str(e["name"]).strip()[:160], "type": e["type"],
                             "quote": str(e.get("quote") or "")[:200], "meta": {"source": "llm"}})
    relations = []
    for r in data.get("relations") or []:
        if (isinstance(r, dict) and r.get("source") and r.get("target")
                and r.get("type") in RELATION_TYPES):
            try:
                conf = float(r.get("confidence") or 0.5)
            except (TypeError, ValueError):
                conf = 0.5
            relations.append({
                "source": str(r["source"]).strip()[:160],
                "source_type": r.get("source_type") if r.get("source_type") in ENTITY_TYPES else "method",
                "target": str(r["target"]).strip()[:160],
                "target_type": r.get("target_type") if r.get("target_type") in ENTITY_TYPES else "method",
                "type": r["type"], "quote": str(r.get("quote") or "")[:200],
                "confidence": min(max(conf, 0.0), 1.0),
            })
    return {"entities": entities, "relations": relations, "findings": []}


def _extract_llm(llm, text: str) -> dict | None:
    try:
        out = llm.complete(_LLM_PROMPT_HEAD + f"\n\n文本：{text[:3000]}", system=_LLM_SYSTEM)
    except Exception as exc:
        logger.warning("LLM 图谱抽取失败（{}），该 chunk 回退规则路径", exc)
        return None
    parsed = _parse_llm_json(out)
    if parsed is None:
        logger.warning("LLM 输出无法解析为 JSON，该 chunk 回退规则路径")
    return parsed


# ---------------- 入库 ----------------
def _get_or_create_entity(db: Database, name: str, etype: str,
                          meta: dict | None = None) -> tuple[int, bool]:
    params = [name, etype]
    row = db.query_one(
        f"SELECT id FROM entities WHERE lower(name) = lower({db.ph}) AND type = {db.ph}", params
    )
    if row:
        return row["id"], False
    db.insert_ignore(
        f"INTO entities (name, type, metadata) VALUES ({db.ph}, {db.ph}, {db.ph})",
        [name, etype, db.dumps(meta or {})],
        conflict_cols="lower(name), type",
    )
    row = db.query_one(
        f"SELECT id FROM entities WHERE lower(name) = lower({db.ph}) AND type = {db.ph}", params
    )
    return (row["id"], True) if row else (0, False)


def _upsert_relation(db: Database, src_id: int, dst_id: int, rtype: str,
                     confidence: float, evidence: dict) -> bool:
    """关系幂等写入；已存在则追加证据（≤20 条）并抬升置信度。返回是否新建。"""
    rid = db.insert_ignore(
        f"INTO relations (source_entity_id, target_entity_id, type, evidence, confidence) "
        f"VALUES ({db.ph}, {db.ph}, {db.ph}, {db.ph}, {db.ph})",
        [src_id, dst_id, rtype, db.dumps([evidence]), confidence],
        conflict_cols="source_entity_id, target_entity_id, type",
    )
    if rid is not None:
        return True
    row = db.query_one(
        f"SELECT id, evidence FROM relations WHERE source_entity_id = {db.ph} "
        f"AND target_entity_id = {db.ph} AND type = {db.ph}",
        [src_id, dst_id, rtype],
    )
    if not row:
        return False
    ev = row.get("evidence") or []
    if not any(e.get("chunk_id") == evidence.get("chunk_id")
               and e.get("quote") == evidence.get("quote") for e in ev):
        ev = (ev + [evidence])[-20:]
        db.execute(
            f"UPDATE relations SET evidence = {db.ph}, "
            f"confidence = CASE WHEN confidence >= {db.ph} THEN confidence ELSE {db.ph} END "
            f"WHERE id = {db.ph}",
            [db.dumps(ev), confidence, confidence, row["id"]],
        )
    return False


# ---------------- 主流程 ----------------
def build_graph(db: Database, settings: Settings | None = None, *, project_id: int,
                use_llm: bool = True) -> dict:
    """对项目的全部 chunks 做实体/关系抽取并入库（幂等），返回执行摘要。"""
    settings = settings or get_settings()
    started = time.perf_counter()
    rows = db.query(
        f"SELECT c.id AS chunk_id, c.text, c.paper_id, p.title AS paper_title "
        f"FROM chunks c JOIN papers p ON p.id = c.paper_id "
        f"JOIN projects_papers pp ON pp.paper_id = p.id "
        f"WHERE pp.project_id = {db.ph} ORDER BY c.id",
        [project_id],
    )
    if not rows:
        raise ValueError(f"项目 {project_id} 没有 chunks，请先运行文献流水线 (literature)")

    llm = _probe_llm(settings) if (use_llm and settings.llm_enabled) else None
    id_map: dict[tuple[str, str], int] = {}
    all_findings: list[dict] = []
    entities_created = relations_created = 0

    def resolve(name: str, etype: str, meta: dict | None, quote: str) -> int:
        nonlocal entities_created
        key = (name.lower(), etype)
        if key in id_map:
            return id_map[key]
        eid, created = _get_or_create_entity(db, name, etype, meta)
        if not eid:
            return 0
        id_map[key] = eid
        entities_created += int(created)
        return eid

    for row in rows:
        chunk_id, paper_id, title = row["chunk_id"], row["paper_id"], row["paper_title"]
        result = (_extract_llm(llm, row["text"]) if llm is not None else None) \
            or _extract_rules(row["text"])

        chunk_entity_names: list[str] = []
        for e in result["entities"]:
            eid = resolve(e["name"], e["type"], e.get("meta"), e.get("quote", ""))
            if eid:
                chunk_entity_names.append(e["name"])

        for rel in result["relations"]:
            src_id = resolve(rel["source"], rel["source_type"], None, rel.get("quote", ""))
            dst_id = resolve(rel["target"], rel["target_type"], None, rel.get("quote", ""))
            if not src_id or not dst_id or src_id == dst_id:
                continue
            evidence = {"chunk_id": chunk_id, "paper_id": paper_id, "title": title,
                        "quote": rel.get("quote", "")}
            relations_created += int(_upsert_relation(
                db, src_id, dst_id, rel["type"], rel["confidence"], evidence))

        for f in result.get("findings", []):
            all_findings.append({**f, "chunk_id": chunk_id, "paper_id": paper_id,
                                 "title": title})

        db.execute(f"UPDATE chunks SET entities = {db.ph} WHERE id = {db.ph}",
                   [db.dumps(chunk_entity_names), chunk_id])

    # 跨论文矛盾配对：同一方法上的正/负极性结论
    contradictions = 0
    by_method: dict[str, dict[str, list[dict]]] = defaultdict(lambda: {"pos": [], "neg": []})
    for f in all_findings:
        for m in f["methods"]:
            by_method[m][f["polarity"]].append(f)
    for method, groups in by_method.items():
        for pf in groups["pos"]:
            for nf in groups["neg"]:
                if pf["paper_id"] == nf["paper_id"]:
                    continue  # 矛盾定义为跨论文结论冲突
                src_id = id_map.get((pf["name"].lower(), "finding"))
                dst_id = id_map.get((nf["name"].lower(), "finding"))
                if not src_id or not dst_id:
                    continue
                evidence = {"chunk_id": pf["chunk_id"], "paper_id": pf["paper_id"],
                            "title": f'{pf["title"]} vs {nf["title"]}',
                            "quote": f'POS[{method}]: {pf["name"]} || NEG: {nf["name"]}'}
                contradictions += int(_upsert_relation(
                    db, src_id, dst_id, "contradicts", 0.5, evidence))

    by_type = {r["type"]: r["n"] for r in db.query(
        "SELECT type, COUNT(*) AS n FROM entities GROUP BY type")}
    total_rels = db.scalar("SELECT COUNT(*) FROM relations")
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info("图谱构建完成 project#{}: 实体+{} / 关系+{} / 矛盾 {} / {:.1f}s",
                project_id, entities_created, relations_created, contradictions,
                elapsed_ms / 1000)
    return {
        "project_id": project_id,
        "chunks_processed": len(rows),
        "entities_created": entities_created,
        "relations_created": relations_created,
        "contradictions": contradictions,
        "findings": len(all_findings),
        "by_type": by_type,
        "relations_total": int(total_rels or 0),
        "llm_used": llm is not None,
        "elapsed_ms": elapsed_ms,
    }
