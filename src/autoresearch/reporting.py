"""报告生成：项目全链路（文献/图谱/假设/实验）汇成带引用的论文初稿（Markdown）。

引用规范：正文 [n] 与文末参考文献一一对应，且全部来自库内真实论文记录
（papers 表），保证引用可溯源（引用准确率 100% 结构性保证）。
"""
from __future__ import annotations

import time
from datetime import date

from loguru import logger

from .config import Settings, get_settings
from .db import Database
from .graph.query import contradictions, entity_stats, gaps, top_entities


def generate_report(db: Database, settings: Settings | None = None, *,
                    project_id: int, top_hypotheses: int = 10) -> dict:
    started = time.perf_counter()
    settings = settings or get_settings()
    project = db.query_one(f"SELECT * FROM projects WHERE id = {db.ph}", [project_id])
    if project is None:
        raise LookupError(f"项目 #{project_id} 不存在")

    papers = db.query(
        f"SELECT p.id, p.title, p.authors, p.year, p.url FROM papers p "
        f"JOIN projects_papers pp ON pp.paper_id = p.id "
        f"WHERE pp.project_id = {db.ph} ORDER BY p.year DESC, p.id LIMIT 15",
        [project_id],
    )
    stats = entity_stats(db)
    n_rel = int(db.scalar("SELECT COUNT(*) FROM relations") or 0)
    top = top_entities(db, limit=8)
    gap_list = gaps(db, limit=5)
    con_list = contradictions(db, limit=5)
    hyps = db.query(
        f"SELECT statement, novelty, metadata, testability FROM hypotheses "
        f"WHERE project_id = {db.ph} ORDER BY novelty DESC LIMIT {int(top_hypotheses)}",
        [project_id],
    )
    exps = db.query(
        f"SELECT e.id AS exp_id, h.statement, h.novelty "
        f"FROM experiments e JOIN hypotheses h ON h.id = e.hypothesis_id "
        f"WHERE h.project_id = {db.ph} ORDER BY e.id",
        [project_id],
    )
    run_rows: list[dict] = []
    for e in exps:
        run = db.query_one(
            f"SELECT id, status, metrics, logs FROM runs WHERE experiment_id = {db.ph} "
            f"ORDER BY id DESC LIMIT 1", [e["exp_id"]],
        )
        if run:
            run_rows.append({**e, "run": run})

    lines: list[str] = []
    figs: list[dict] = []
    q = project["question"]
    lines.append(f"# {q}")
    lines.append("")
    lines.append(f"> AutoResearch 自动生成研究报告 · 项目 #{project_id} · {project['domain']} · {date.today()}")
    lines.append("")
    n_papers = len(papers)
    n_ents = sum(stats.values())
    lines.append("## 摘要")
    lines.append("")
    lines.append(
        f"本项目围绕研究问题「{q}」，基于 {n_papers} 篇文献构建了包含 {n_ents} 个实体、"
        f"{n_rel} 条关系的知识图谱，自动提出 {len(hyps)} 条可验证假设，"
        f"并对 {len(run_rows)} 个实验完成自动化执行与统计分析。"
        f"整体流程（文献检索 → 图谱构建 → 假设生成 → 实验执行 → 结果分析）由 AutoResearch 自动完成，"
        f"所有实验代码与结果可复现。"
    )
    lines.append("")

    lines.append("## 1. 相关工作")
    lines.append("")
    for i, p in enumerate(papers, 1):
        year = p.get("year") or "n.d."
        lines.append(f"- {p['title']} ({year}) [{i}]")
    lines.append("")

    lines.append("## 2. 知识图谱发现")
    lines.append("")
    lines.append("| 类型 | 数量 |")
    lines.append("|---|---|")
    for etype in ("method", "dataset", "metric", "finding", "gap"):
        lines.append(f"| {etype} | {stats.get(etype, 0)} |")
    lines.append("")
    lines.append("头部实体：" + "、".join(f"{r['name']}（度 {r['degree']}）" for r in top[:5]))
    lines.append("")
    if gap_list:
        lines.append("**研究缺口（示例）**")
        lines.append("")
        for g in gap_list[:3]:
            lines.append(f"- {g['name'][:120]}")
        lines.append("")
    if con_list:
        lines.append("**跨论文矛盾（示例）**")
        lines.append("")
        for citem in con_list[:3]:
            lines.append(f"- 「{citem['finding_a'][:80]}」 ↔ 「{citem['finding_b'][:80]}」")
        lines.append("")

    lines.append("## 3. 研究假设")
    lines.append("")
    for i, h in enumerate(hyps, 1):
        lines.append(f"{i}. （novelty={h['novelty']:.2f}）{h['statement']}")
    lines.append("")

    lines.append("## 4. 实验与结果")
    lines.append("")
    if run_rows:
        lines.append("| 实验 | 数据集 | 指标 | 基线 | 提出 | Δ | p | 结论 |")
        lines.append("|---|---|---|---|---|---|---|---|")
        verdict_cn = {"significant_improvement": "显著提升", "improvement_not_significant": "提升(不显著)",
                      "significant_degradation": "显著下降", "degradation_not_significant": "下降(不显著)"}
        for r in run_rows:
            metrics = r["run"].get("metrics") or {}
            analysis = metrics.get("analysis") or {}
            for item in (analysis.get("per_item") or [])[:3]:
                lines.append(
                    f"| #{r['exp_id']} | {item['dataset']} | {item['metric']} "
                    f"| {item['mean_baseline']} | {item['mean_proposed']} "
                    f"| {item['mean_diff']:+.4f} | {item['sign_test_p']:.3f} "
                    f"| {verdict_cn.get(item['verdict'], item['verdict'])} |"
                )
                figs.append({
                    "title": f"实验#{r['exp_id']} {item['dataset']} · {item['metric']}",
                    "data": {"baseline": item["mean_baseline"], "proposed": item["mean_proposed"]},
                })
        lines.append("")
        lines.append("统计检验：逐折配对差的精确符号检验（α=0.05）。完整结果见各实验工作区 results.json。")
    else:
        lines.append("（尚未执行实验：通过 `POST /hypotheses/{id}/experiments` 与 `POST /experiments/{id}/run` 生成并运行）")
    lines.append("")

    lines.append("## 5. 结论与局限")
    lines.append("")
    lines.append(
        "- 本报告由自动化流水线生成，假设与实验设计来自知识图谱的证据结构；"
        "代理实验验证的是流程与统计框架，结论外推需接入真实任务数据集。"
    )
    lines.append(
        f"- 局限：文献规模 {n_papers} 篇、离线词典/模板路径（LLM 可用时实体与假设质量更高）；"
        "沙箱执行依赖 Docker 环境。"
    )
    lines.append("")

    lines.append("## 参考文献")
    lines.append("")
    for i, p in enumerate(papers, 1):
        authors = p.get("authors") or []
        authors_str = ", ".join(authors[:3]) + ("等" if len(authors) > 3 else "")
        lines.append(f"[{i}] {authors_str} ({p.get('year') or 'n.d.'}). {p['title']}. {p.get('url') or ''}")
    lines.append("")

    content = "\n".join(lines)
    rid = db.insert(
        f"INSERT INTO reports (project_id, content, citations, figures, status) "
        f"VALUES ({db.ph}, {db.ph}, {db.ph}, {db.ph}, {db.ph})",
        [project_id, content, db.dumps(
            [{"n": i, "paper_id": p["id"], "title": p["title"], "year": p.get("year"),
              "url": p.get("url")} for i, p in enumerate(papers, 1)]),
         db.dumps(figs), "draft"],
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info("报告 #{} 已生成 project#{}: {} 字符 / {} 引用 / {} 图表数据",
                rid, project_id, len(content), len(papers), len(figs))
    return {"report_id": rid, "content": content, "citations_count": len(papers),
            "figures_count": len(figs), "elapsed_ms": elapsed_ms,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
