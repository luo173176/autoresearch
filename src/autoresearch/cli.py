"""autoresearch 命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import Settings, get_settings


def run_init(settings: Settings | None = None) -> int:
    s = settings or get_settings()
    s.ensure_dirs()
    from .db import Database

    db = Database(s)
    ran = db.migrate()
    print(f"[init] 后端: {db.backend}" + (f" ({db.path})" if db.path else ""))
    print(f"[init] 迁移: {', '.join(ran) if ran else '已是最新'}")
    print(f"[init] 数据目录: {s.data_dir}")
    print(f"[init] LLM: {s.llm_base_url} | model={s.llm_model} | cache={s.llm_cache_dir}")
    print("[init] 完成。下一步: `autoresearch serve` 启动 API，`autoresearch ui` 打开看板")
    return 0


def run_literature(
    query: str,
    project: int | None = None,
    max_results: int | None = None,
    sources: str = "arxiv",
    download_pdfs: bool = False,
    pdf_limit: int = 10,
    use_llm: bool = True,
    settings: Settings | None = None,
) -> int:
    """检索文献并入库：缺项目则自动创建；缺 query 时使用项目研究问题。"""
    s = settings or get_settings()
    s.ensure_dirs()
    from .db import Database
    from .literature import run_pipeline

    db = Database(s)
    db.migrate()  # 自愈：库未初始化/落后迁移时先补齐（幂等）
    if project is None:
        pid = db.insert(
            f"INSERT INTO projects (name, question) VALUES ({db.ph}, {db.ph})",
            [query[:80], query],
        )
        print(f"[literature] 已创建项目 #{pid}")
    else:
        pid = project
    proj = db.query_one(f"SELECT * FROM projects WHERE id = {db.ph}", [pid])
    if proj is None:
        print(f"[literature] 项目 #{pid} 不存在")
        return 1

    source_list = [x.strip() for x in sources.split(",") if x.strip()]
    summary = run_pipeline(
        db,
        s,
        project=proj,
        query=query,
        sources=source_list,
        max_results=max_results or s.literature_max_results,
        download_pdfs=download_pdfs,
        pdf_limit=pdf_limit,
        use_llm=use_llm,
    )
    print("[literature] 结果:", json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["papers_found"] else 1


def run_graph(
    project: int | None = None,
    use_llm: bool = True,
    export: str | None = None,
    settings: Settings | None = None,
) -> int:
    """构建项目知识图谱（缺省取最新项目）；可导出 JSON 子图。"""
    s = settings or get_settings()
    s.ensure_dirs()
    from .db import Database
    from .graph import build_graph
    from .graph.query import export_graph

    db = Database(s)
    db.migrate()
    if project is None:
        row = db.query_one("SELECT id FROM projects ORDER BY id DESC LIMIT 1")
        if row is None:
            print("[graph] 无项目。请先运行 `autoresearch literature`")
            return 1
        project = row["id"]
    if db.query_one(f"SELECT id FROM projects WHERE id = {db.ph}", [project]) is None:
        print(f"[graph] 项目 #{project} 不存在")
        return 1
    try:
        summary = build_graph(db, s, project_id=project, use_llm=use_llm)
    except ValueError as exc:
        print(f"[graph] {exc}")
        return 1
    print("[graph] 结果:", json.dumps(summary, ensure_ascii=False, indent=2))
    if export:
        data = export_graph(db, project, Path(export))
        print(f"[graph] 已导出: {export} (nodes={len(data['nodes'])}, links={len(data['links'])})")
    return 0


def run_hypotheses(
    project: int | None = None,
    max_hypotheses: int | None = None,
    use_llm: bool = True,
    settings: Settings | None = None,
) -> int:
    """基于项目图谱生成假设（缺省取最新项目）。"""
    s = settings or get_settings()
    s.ensure_dirs()
    from .db import Database
    from .hypotheses import generate_hypotheses

    db = Database(s)
    db.migrate()
    if project is None:
        row = db.query_one("SELECT id FROM projects ORDER BY id DESC LIMIT 1")
        if row is None:
            print("[hypotheses] 无项目。请先运行 `autoresearch literature`")
            return 1
        project = row["id"]
    if db.query_one(f"SELECT id FROM projects WHERE id = {db.ph}", [project]) is None:
        print(f"[hypotheses] 项目 #{project} 不存在")
        return 1
    try:
        summary = generate_hypotheses(
            db, s, project_id=project, max_hypotheses=max_hypotheses or 50, use_llm=use_llm
        )
    except ValueError as exc:
        print(f"[hypotheses] {exc}")
        return 1
    print("[hypotheses] 结果:", json.dumps(summary, ensure_ascii=False, indent=2))
    top = db.query(
        f"SELECT statement, novelty FROM hypotheses WHERE project_id = {db.ph} "
        f"ORDER BY novelty DESC LIMIT 5",
        [project],
    )
    for i, row in enumerate(top, 1):
        print(f"[hypotheses] Top{i} (novelty={row['novelty']:.2f}): {row['statement'][:90]}")
    return 0


def run_experiment_cmd(
    hypothesis: int | None = None, run: bool = False, settings: Settings | None = None
) -> int:
    """由假设生成实验（缺省取 novelty 最高的假设）；--run 直接执行。"""
    s = settings or get_settings()
    s.ensure_dirs()
    from .db import Database
    from .experiments import create_experiment, run_experiment

    db = Database(s)
    db.migrate()
    if hypothesis is None:
        row = db.query_one("SELECT id FROM hypotheses ORDER BY novelty DESC, id LIMIT 1")
        if row is None:
            print("[experiment] 无假设。请先运行 `autoresearch hypotheses`")
            return 1
        hypothesis = row["id"]
    try:
        created = create_experiment(db, s, hypothesis_id=hypothesis)
    except LookupError as exc:
        print(f"[experiment] {exc}")
        return 1
    print(f"[experiment] 实验 #{created['experiment_id']} 已生成 → {created['workspace']}")
    print(f"[experiment] 文件: {', '.join(created['files'])}")
    if run:
        result = run_experiment(db, s, experiment_id=created["experiment_id"])
        print(f"[experiment] 执行结果: {json.dumps(result, ensure_ascii=False, indent=2)[:1500]}")
        return 0 if result["status"] == "completed" else 1
    return 0


def run_run(experiment_id: int, settings: Settings | None = None) -> int:
    """执行已生成的实验（沙箱/本地自动选择，失败重试）。"""
    s = settings or get_settings()
    from .db import Database
    from .experiments import run_experiment

    db = Database(s)
    db.migrate()
    try:
        result = run_experiment(db, s, experiment_id=experiment_id)
    except LookupError as exc:
        print(f"[run] {exc}")
        return 1
    print(f"[run] 结果: {json.dumps(result, ensure_ascii=False, indent=2)[:1500]}")
    return 0 if result["status"] == "completed" else 1


def run_report(
    project: int | None = None, export: str | None = None, settings: Settings | None = None
) -> int:
    """生成项目研究报告（论文初稿，带引用）。"""
    s = settings or get_settings()
    from .db import Database
    from .reporting import generate_report

    db = Database(s)
    db.migrate()
    if project is None:
        row = db.query_one("SELECT id FROM projects ORDER BY id DESC LIMIT 1")
        if row is None:
            print("[report] 无项目")
            return 1
        project = row["id"]
    try:
        result = generate_report(db, s, project_id=project)
    except LookupError as exc:
        print(f"[report] {exc}")
        return 1
    print(
        f"[report] 报告 #{result['report_id']} 已生成（引用 {result['citations_count']} 篇 / "
        f"图表 {result['figures_count']} 组）"
    )
    if export:
        Path(export).parent.mkdir(parents=True, exist_ok=True)
        Path(export).write_text(result["content"], encoding="utf-8")
        print(f"[report] 已导出: {export}")
    else:
        print(result["content"][:1200])
    return 0


def run_watch(
    project: int | None = None,
    interval: int = 600,
    once: bool = False,
    max_results: int = 10,
    settings: Settings | None = None,
) -> int:
    """定时扫描新论文并刷新图谱/假设（--once 单轮，便于测试）。"""
    import time as _time

    s = settings or get_settings()
    from .db import Database
    from .graph import build_graph
    from .hypotheses import generate_hypotheses
    from .literature import run_pipeline

    db = Database(s)
    db.migrate()
    if project is None:
        row = db.query_one("SELECT id FROM projects ORDER BY id DESC LIMIT 1")
        if row is None:
            print("[watch] 无项目")
            return 1
        project = row["id"]
    project_row = db.query_one(f"SELECT * FROM projects WHERE id = {db.ph}", [project])
    if project_row is None:
        print(f"[watch] 项目 #{project} 不存在")
        return 1

    while True:
        lit = run_pipeline(db, s, project=project_row, max_results=max_results)
        graph = build_graph(db, s, project_id=project)
        hyp = generate_hypotheses(db, s, project_id=project, max_hypotheses=30)
        print(
            f"[watch] 轮次完成: 论文+{lit['papers_new']} / 关系+{graph['relations_created']} "
            f"/ 假设+{hyp['stored']} (db: {db.backend})"
        )
        if once:
            return 0
        _time.sleep(interval)


def run_eval_cmd(max_questions: int = 3, settings: Settings | None = None) -> int:
    """端到端评估（需外网）：eval/questions.jsonl 逐题跑全流水线。"""
    from .eval.run_eval import run_eval

    s = settings or get_settings()
    out = run_eval(max_questions=max_questions, settings=s)
    print(json.dumps(out, ensure_ascii=False, indent=2)[:2000])
    return 0


def run_auto(
    question: str,
    max_results: int = 30,
    sources: str = "arxiv",
    with_experiment: bool = True,
    settings: Settings | None = None,
) -> int:
    """一键全流程：文献 → 图谱 → 假设 → 实验 → 报告。"""
    s = settings or get_settings()
    s.ensure_dirs()
    if run_literature(question, max_results=max_results, sources=sources, settings=s) != 0:
        return 1
    from .db import Database

    db = Database(s)
    pid = db.query_one("SELECT id FROM projects ORDER BY id DESC LIMIT 1")["id"]
    if run_graph(project=pid, use_llm=True, settings=s) != 0:
        return 1
    if run_hypotheses(project=pid, max_hypotheses=30, settings=s) != 0:
        return 1
    if with_experiment:
        top = db.query_one(
            f"SELECT id FROM hypotheses WHERE project_id = {db.ph} "
            f"ORDER BY novelty DESC, id LIMIT 1",
            [pid],
        )
        if top is None:
            print("[auto] 未生成假设，跳过实验")
        elif run_experiment_cmd(hypothesis=top["id"], run=True, settings=s) != 0:
            print("[auto] 实验失败，继续生成报告（结果表将留空）")
    export = str(Path(s.data_dir) / "artifacts" / f"report_project{pid}.md")
    if run_report(project=pid, export=export, settings=s) != 0:
        return 1
    print(f"[auto] ✅ 完成！项目 #{pid} · 报告: {export}")
    print("[auto] 打开看板查看全部产出: autoresearch ui")
    return 0


def run_config(test: bool = False, settings: Settings | None = None) -> int:
    """查看当前 LLM 配置（key 打码）；--test 真实发一条消息验证连通性。"""
    s = settings or get_settings()

    def mask(key: str) -> str:
        if not key or key == "ollama":
            return key or "（空）"
        return f"{key[:4]}****{key[-4:]}" if len(key) > 8 else "****"

    env_path = Path.cwd() / ".env"
    print(f"配置文件: {env_path}（存在: {env_path.exists()}；看板「⚙️ 设置」页可图形化修改）")
    print(f"LLM  base_url = {s.llm_base_url}")
    print(f"LLM  model    = {s.llm_model}")
    print(f"LLM  api_key  = {mask(s.llm_api_key)}")
    print(f"LLM  enabled  = {s.llm_enabled}")
    print(f"嵌入  {s.embed_base_url} | {s.embed_model}")
    print(f"重排  {s.rerank_base_url} | {s.rerank_model}")
    if test:
        from .llm.client import verify_llm_connection

        ok, msg = verify_llm_connection(s.llm_base_url, s.llm_api_key, s.llm_model)
        print(("[OK] " if ok else "[FAIL] ") + msg)
        return 0 if ok else 1
    return 0


def run_serve(
    host: str | None = None, port: int | None = None, settings: Settings | None = None
) -> int:
    s = settings or get_settings()
    import uvicorn

    uvicorn.run(
        "autoresearch.api.main:create_app",
        factory=True,
        host=host or s.api_host,
        port=port or s.api_port,
    )
    return 0


def run_ui(port: int | None = None, settings: Settings | None = None) -> int:
    import subprocess
    from pathlib import Path

    s = settings or get_settings()
    app_path = Path(__file__).resolve().parent / "ui" / "app.py"
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        "--server.port",
        str(port or s.ui_port),
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]
    print("[ui] Streamlit 启动中:", " ".join(cmd))
    return subprocess.call(cmd)


def run_worker(
    interval: float = 1.0,
    once: bool = False,
    workers: int | None = None,
    batch: int = 20,
    settings: Settings | None = None,
) -> int:
    """运行独立数据库队列 worker，与 API 进程解耦。"""
    from .worker import run_worker as _run_worker

    return _run_worker(
        settings or get_settings(),
        interval=interval,
        once=once,
        max_workers=workers,
        batch_size=batch,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="autoresearch", description="AutoResearch 自主科研与实验平台"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="初始化数据目录与数据库迁移")
    p_lit = sub.add_parser("literature", help="检索文献并入库（arXiv/S2/PubMed）")
    p_lit.add_argument("query", help="研究问题或关键词")
    p_lit.add_argument("--project", type=int, default=None, help="项目 ID（缺省自动创建）")
    p_lit.add_argument("--max", type=int, default=None, help="每源最大篇数")
    p_lit.add_argument("--sources", default="arxiv", help="逗号分隔：arxiv,s2,pubmed")
    p_lit.add_argument("--download-pdfs", action="store_true", help="下载并解析 PDF 全文")
    p_lit.add_argument("--pdf-limit", type=int, default=10, help="最多下载的 PDF 数")
    p_lit.add_argument("--no-llm", action="store_true", help="禁用 LLM 增强（纯启发式抽取）")
    p_graph = sub.add_parser("graph", help="构建项目知识图谱")
    p_graph.add_argument("--project", type=int, default=None, help="项目 ID（缺省取最新项目）")
    p_graph.add_argument("--no-llm", action="store_true", help="禁用 LLM 抽取（规则词典路径）")
    p_graph.add_argument("--export", default=None, help="导出子图 JSON 到指定路径")
    p_hyp = sub.add_parser("hypotheses", help="基于项目图谱生成研究假设")
    p_hyp.add_argument("--project", type=int, default=None, help="项目 ID（缺省取最新项目）")
    p_hyp.add_argument("--max", type=int, default=None, help="最多生成的假设条数")
    p_hyp.add_argument("--no-llm", action="store_true", help="禁用 LLM（纯规则模板）")
    p_exp = sub.add_parser("experiment", help="由假设生成实验代码包")
    p_exp.add_argument(
        "--hypothesis", type=int, default=None, help="假设 ID（缺省取 novelty 最高）"
    )
    p_exp.add_argument("--run", action="store_true", help="生成后立即执行")
    p_run = sub.add_parser("run", help="执行实验")
    p_run.add_argument("experiment_id", type=int)
    p_rep = sub.add_parser("report", help="生成研究报告（论文初稿）")
    p_rep.add_argument("--project", type=int, default=None)
    p_rep.add_argument("--export", default=None, help="导出 Markdown 路径")
    p_watch = sub.add_parser("watch", help="定时扫描新论文并刷新图谱/假设")
    p_watch.add_argument("--project", type=int, default=None)
    p_watch.add_argument("--interval", type=int, default=600, help="轮询间隔秒数")
    p_watch.add_argument("--once", action="store_true", help="只跑一轮")
    sub.add_parser("eval", help="端到端评估（需外网）")
    p_cfg = sub.add_parser("config", help="查看大模型配置（--test 验证连通性）")
    p_cfg.add_argument("--test", action="store_true", help="真实发送一条测试消息")
    p_auto = sub.add_parser("auto", help="一键全流程：文献→图谱→假设→实验→报告")
    p_auto.add_argument("question", help="研究问题")
    p_auto.add_argument("--max", type=int, default=30, help="每源检索篇数")
    p_auto.add_argument("--sources", default="arxiv", help="逗号分隔：arxiv,s2,pubmed")
    p_auto.add_argument("--no-experiment", action="store_true", help="跳过实验执行")
    p_serve = sub.add_parser("serve", help="启动 FastAPI 服务")
    p_serve.add_argument("--host", default=None)
    p_serve.add_argument("--port", type=int, default=None)
    p_ui = sub.add_parser("ui", help="启动 Streamlit 看板")
    p_ui.add_argument("--port", type=int, default=None)
    p_worker = sub.add_parser("worker", help="运行独立后台任务 worker")
    p_worker.add_argument("--interval", type=float, default=1.0, help="队列轮询间隔秒数")
    p_worker.add_argument("--once", action="store_true", help="处理当前队列后退出")
    p_worker.add_argument("--workers", type=int, default=None, help="worker 线程数")
    p_worker.add_argument("--batch", type=int, default=20, help="每轮最多领取任务数")
    sub.add_parser("version", help="打印版本")

    args = parser.parse_args(argv)
    if args.command == "init":
        return run_init()
    if args.command == "literature":
        return run_literature(
            args.query,
            project=args.project,
            max_results=args.max,
            sources=args.sources,
            download_pdfs=args.download_pdfs,
            pdf_limit=args.pdf_limit,
            use_llm=not args.no_llm,
        )
    if args.command == "graph":
        return run_graph(project=args.project, use_llm=not args.no_llm, export=args.export)
    if args.command == "hypotheses":
        return run_hypotheses(
            project=args.project, max_hypotheses=args.max, use_llm=not args.no_llm
        )
    if args.command == "experiment":
        return run_experiment_cmd(hypothesis=args.hypothesis, run=args.run)
    if args.command == "run":
        return run_run(args.experiment_id)
    if args.command == "report":
        return run_report(project=args.project, export=args.export)
    if args.command == "watch":
        return run_watch(project=args.project, interval=args.interval, once=args.once)
    if args.command == "eval":
        return run_eval_cmd()
    if args.command == "config":
        return run_config(test=args.test)
    if args.command == "auto":
        return run_auto(
            args.question,
            max_results=args.max,
            sources=args.sources,
            with_experiment=not args.no_experiment,
        )
    if args.command == "serve":
        return run_serve(args.host, args.port)
    if args.command == "ui":
        return run_ui(args.port)
    if args.command == "worker":
        return run_worker(args.interval, args.once, args.workers, args.batch)
    if args.command == "version":
        print(f"AutoResearch {__version__}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
