"""AutoResearch Streamlit 看板：总览 / 图谱 / 实验 / 报告。"""
from __future__ import annotations

import json

import streamlit as st

st.set_page_config(page_title="AutoResearch", page_icon="🔬", layout="wide")

st.title("🔬 AutoResearch 平台看板")
st.caption("文献调研 → 知识图谱 → 假设生成 → 实验执行 → 论文报告")


@st.cache_resource
def _get_db():
    from autoresearch.db import Database

    return Database()


def _count(table: str) -> int:
    try:
        return int(db.scalar(f"SELECT COUNT(*) FROM {table}") or 0)
    except Exception:
        return 0


db = _get_db()

page = st.sidebar.radio("页面", ["🚀 一键研究", "⚙️ 设置", "📊 项目总览", "🕸 图谱浏览",
                                "🧪 实验运行", "📄 报告查看"])

projects: list[dict] = []
db_ready = db.healthy()
if db_ready:
    try:
        projects = db.query("SELECT id, name, question, status FROM projects ORDER BY id DESC LIMIT 50")
    except Exception as exc:  # 表尚未迁移
        st.warning(f"数据表未就绪，请运行 `autoresearch init`：{exc}")
else:
    st.warning("数据库未连接。请先运行 `autoresearch init`（或通过 Docker Compose 启动 PostgreSQL）。")


def _project_picker() -> int | None:
    if not projects:
        st.info("暂无项目。先运行 `autoresearch literature \"问题\"` 创建。")
        return None
    return st.sidebar.selectbox(
        "选择项目", options=[p["id"] for p in projects],
        format_func=lambda i: f"#{i} {next(p['name'] for p in projects if p['id'] == i)}",
    )


def render_auto() -> None:
    """一键研究：输入问题 → 文献→图谱→假设→实验→报告 全自动。"""
    from autoresearch.config import get_settings

    st.header("🚀 一键研究")
    st.caption("输入研究问题，自动完成：文献检索 → 知识图谱 → 假设生成 → 实验执行 → 研究报告（约 1-3 分钟）")

    default_q = "检索增强生成（RAG）中，重排模型对端到端问答准确率提升多少？"
    question = st.text_input("研究问题", value=default_q)
    c1, c2 = st.columns(2)
    max_results = c1.slider("检索篇数", 10, 100, 30, 10)
    domain = c2.selectbox("领域", ["IR", "NLP", "ML", "general"], index=0)

    if not st.button("▶ 开始自动研究", type="primary", disabled=not db_ready or not question.strip()):
        st.info("点击按钮开始；无需任何 API Key，LLM 可用时自动增强，不可用时走内置词典规则。")
        return

    settings = get_settings()
    pid = None
    try:
        with st.status("自动研究进行中…", expanded=True) as status:
            st.write("① 创建项目…")
            pid = db.insert(
                f"INSERT INTO projects (name, question, domain) VALUES ({db.ph}, {db.ph}, {db.ph})",
                [question[:80], question, domain],
            )
            project = db.query_one(f"SELECT * FROM projects WHERE id = {db.ph}", [pid])

            st.write(f"② 文献检索与解析（arXiv，{max_results} 篇）…")
            from autoresearch.literature import run_pipeline

            lit = run_pipeline(db, settings, project=project, sources=["arxiv"],
                               max_results=max_results)
            st.write(f"   ✅ 论文 {lit['papers_found']} 篇（新增 {lit['papers_new']}）/ "
                     f"chunks {lit['chunks_created']}")

            st.write("③ 构建知识图谱…")
            from autoresearch.graph import build_graph

            graph = build_graph(db, settings, project_id=pid)
            st.write(f"   ✅ 实体 +{graph['entities_created']} / 关系 +{graph['relations_created']} "
                     f"/ 矛盾 {graph['contradictions']} 对")

            st.write("④ 生成研究假设…")
            from autoresearch.hypotheses import generate_hypotheses

            hyp = generate_hypotheses(db, settings, project_id=pid, max_hypotheses=30)
            st.write(f"   ✅ {hyp['generated']} 条（{hyp['by_source']}）")

            st.write("⑤ 生成并执行实验…")
            from autoresearch.experiments import create_experiment, run_experiment

            top = db.query_one(
                f"SELECT id, statement FROM hypotheses WHERE project_id = {db.ph} "
                f"ORDER BY novelty DESC, id LIMIT 1", [pid],
            )
            run_summary = None
            if top:
                created = create_experiment(db, settings, hypothesis_id=top["id"])
                st.write(f"   实验包 → {created['workspace']}")
                run_summary = run_experiment(db, settings, experiment_id=created["experiment_id"])
                st.write(f"   ✅ 执行 {run_summary['status']}（executor={run_summary.get('executor')}）")

            st.write("⑥ 生成研究报告…")
            from autoresearch.reporting import generate_report

            report = generate_report(db, settings, project_id=pid)
            status.update(label="🎉 全流程完成", state="complete", expanded=False)
    except Exception as exc:
        st.error(f"流程中断（项目 #{pid}）：{exc}")
        st.warning("可切到其他页面查看已完成部分的产出；重试通常是安全的（全链路幂等）。")
        return

    st.success(f"项目 #{pid} 全流程完成！可在左侧切换查看图谱/实验/报告。")
    if run_summary and run_summary.get("status") == "completed":
        analysis = run_summary.get("analysis") or {}
        st.metric("实验整体结论", analysis.get("overall"))
        st.write("**迭代建议**：", "；".join(analysis.get("suggestions", [])))
    st.markdown(report["content"])
    st.download_button("下载报告 Markdown", data=report["content"],
                       file_name=f"report_project{pid}.md", mime="text/markdown")


def _mask(key: str) -> str:
    if not key or key == "ollama":
        return key or "（空）"
    return f"{key[:4]}****{key[-4:]}" if len(key) > 8 else "****"


def render_settings() -> None:
    """大模型 API 设置：填 base_url/Key/模型 → 测试连接 → 保存到 .env 立即生效。"""
    from autoresearch.config import get_settings, reload_settings, save_env_values
    from autoresearch.literature.extractor import reset_llm_probe_cache
    from autoresearch.llm.client import verify_llm_connection

    st.header("⚙️ 大模型 API 设置")
    st.caption("配置写入项目根目录 `.env`（明文，已在 .gitignore 中）；保存后立即生效，无需重启。"
               "模型名会自动参与 LLM 缓存键，换模型不会读到旧缓存。")

    settings = get_settings()
    presets = {
        "Ollama（本机，免费）": ("http://localhost:11434/v1", "qwen2.5:7b"),
        "DeepSeek": ("https://api.deepseek.com/v1", "deepseek-chat"),
        "OpenAI": ("https://api.openai.com/v1", "gpt-4o-mini"),
        "智谱 GLM": ("https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"),
        "自定义": ("", ""),
    }
    preset = st.selectbox("快捷预设（自动填充地址与模型名）", list(presets.keys()),
                          index=0 if settings.llm_base_url.endswith("11434/v1") else 4)
    preset_url, preset_model = presets[preset]
    base_url = st.text_input("Base URL（OpenAI 兼容接口）",
                             value=preset_url or settings.llm_base_url)
    model = st.text_input("模型名", value=preset_model or settings.llm_model)
    api_key = st.text_input(
        "API Key",
        value="",
        type="password",
        placeholder=f"已配置（{_mask(settings.llm_api_key)}），留空则沿用旧值",
        help="Ollama 本地服务无需真实 Key（随意填即可）",
    )
    llm_enabled = st.toggle("启用 LLM 增强（关闭则全部走内置词典规则，零外部依赖）",
                            value=settings.llm_enabled)

    col_test, col_save, _ = st.columns([1, 1, 2])
    do_test = col_test.button("🔍 测试连接", use_container_width=True)
    do_save = col_save.button("💾 保存配置", type="primary", use_container_width=True)

    effective_key = api_key.strip() or settings.llm_api_key
    if do_test:
        with st.spinner("发送测试消息（最长 20 秒）…"):
            ok, msg = verify_llm_connection(base_url, effective_key, model)
        (st.success if ok else st.error)(msg)

    if do_save:
        save_env_values({
            "AUTORESEARCH_LLM_BASE_URL": base_url.strip(),
            "AUTORESEARCH_LLM_API_KEY": effective_key,
            "AUTORESEARCH_LLM_MODEL": model.strip(),
            "AUTORESEARCH_LLM_ENABLED": "true" if llm_enabled else "false",
        })
        new_settings = reload_settings()
        reset_llm_probe_cache()
        st.success(
            f"已保存并立即生效：{new_settings.llm_base_url} | {new_settings.llm_model} | "
            f"enabled={new_settings.llm_enabled}。去「🚀 一键研究」即可用大模型增强。"
        )

    with st.expander("高级：嵌入 / 重排模型（检索阶段使用，可暂不配置）"):
        e_url = st.text_input("嵌入 Base URL", value=settings.embed_base_url)
        e_model = st.text_input("嵌入模型", value=settings.embed_model)
        r_url = st.text_input("重排 Base URL", value=settings.rerank_base_url)
        r_model = st.text_input("重排模型", value=settings.rerank_model)
        if st.button("保存嵌入/重排配置"):
            save_env_values({
                "AUTORESEARCH_EMBED_BASE_URL": e_url.strip(),
                "AUTORESEARCH_EMBED_MODEL": e_model.strip(),
                "AUTORESEARCH_RERANK_BASE_URL": r_url.strip(),
                "AUTORESEARCH_RERANK_MODEL": r_model.strip(),
            })
            reload_settings()
            st.success("已保存。")

    st.divider()
    st.caption(
        f"当前生效：base_url=`{settings.llm_base_url}` · model=`{settings.llm_model}` · "
        f"key=`{_mask(settings.llm_api_key)}` · enabled={settings.llm_enabled}"
    )


def render_overview() -> None:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("项目", len(projects))
    c2.metric("文献", _count("papers"))
    c3.metric("Chunks", _count("chunks"))
    c4.metric("假设", _count("hypotheses"))
    c5.metric("实验", _count("experiments"))
    st.subheader("项目")
    if projects:
        st.dataframe(projects, use_container_width=True)
    else:
        st.info("通过 `POST /projects` 或 CLI `autoresearch literature \"问题\"` 创建。")


def render_graph() -> None:
    from autoresearch.graph.query import (
        contradictions,
        entity_stats,
        export_graph,
        gaps,
        neighbors,
        top_entities,
    )

    pid = _project_picker()
    if pid is None:
        return
    stats = entity_stats(db)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("实体总数", sum(stats.values()))
    c2.metric("方法", stats.get("method", 0))
    c3.metric("数据集/指标", stats.get("dataset", 0) + stats.get("metric", 0))
    c4.metric("结论/缺口", stats.get("finding", 0) + stats.get("gap", 0))
    c5.metric("关系数", _count("relations"))

    left, right = st.columns(2)
    with left:
        st.subheader("头部实体（按关系度）")
        st.dataframe(top_entities(db, limit=15), use_container_width=True)
    with right:
        st.subheader("邻居查询")
        names = [r["name"] for r in top_entities(db, limit=50)]
        if names:
            pick = st.selectbox("实体", names)
            st.dataframe(neighbors(db, pick), use_container_width=True)
        else:
            st.caption("暂无实体")

    with st.expander(f"研究缺口（{len(gaps(db))}）"):
        st.dataframe(gaps(db), use_container_width=True)
    with st.expander(f"矛盾清单（{len(contradictions(db))}）"):
        st.dataframe(contradictions(db), use_container_width=True)

    data = export_graph(db, pid)
    st.download_button("下载子图 JSON", data=json.dumps(data, ensure_ascii=False, indent=2),
                       file_name=f"graph_project{pid}.json", mime="application/json")
    st.caption(f"子图规模：{len(data['nodes'])} 节点 / {len(data['links'])} 边")


def render_experiments() -> None:
    try:
        exps = db.query(
            "SELECT e.id, e.status, e.code_path, h.statement FROM experiments e "
            "JOIN hypotheses h ON h.id = e.hypothesis_id ORDER BY e.id DESC LIMIT 30"
        )
    except Exception:
        exps = []
    if not exps:
        st.info("暂无实验。通过 `POST /hypotheses/{id}/experiments` 或 CLI `autoresearch experiment` 生成。")
        return
    eid = st.selectbox("选择实验", options=[e["id"] for e in exps],
                       format_func=lambda i: f"#{i} {next(e['statement'][:40] for e in exps if e['id'] == i)}")
    exp = next(e for e in exps if e["id"] == eid)
    st.caption(f"状态: {exp['status']} · 工作区: {exp['code_path']}")
    runs = db.query(f"SELECT * FROM runs WHERE experiment_id = {db.ph} ORDER BY id DESC", [eid])
    if not runs:
        st.info("尚未执行。CLI: `autoresearch run {id}`".format(id=eid))
        return
    run = runs[0]
    st.metric("最新 Run", f"#{run['id']} · {run['status']}")
    analysis = ((run.get("metrics") or {}).get("analysis") or {})
    st.json(analysis.get("per_item", []) if analysis else {"note": "run 未完成"})
    if analysis:
        c1, c2 = st.columns(2)
        c1.metric("整体结论", analysis.get("overall"))
        c2.metric("显著提升/下降", f"{analysis.get('n_improvements', 0)} / {analysis.get('n_degradations', 0)}")
        rows = analysis.get("per_item") or []
        if rows:
            st.bar_chart({f"{r['dataset']}·{r['metric']}": {r2: v for r2, v in
                          [("baseline", r["mean_baseline"]), ("proposed", r["mean_proposed"])]}
                          for r in rows})
        st.write("**迭代建议**:", "；".join(analysis.get("suggestions", [])))
    with st.expander("历史 Runs"):
        st.dataframe([{k: r[k] for k in ("id", "status")} for r in runs], use_container_width=True)


def render_report() -> None:
    from autoresearch.reporting import generate_report

    pid = _project_picker()
    if pid is None:
        return
    if st.button("生成新报告"):
        try:
            result = generate_report(db, project_id=pid)
            st.success(f"报告 #{result['report_id']} 已生成（引用 {result['citations_count']} 篇）")
        except Exception as exc:
            st.error(f"生成失败：{exc}")
    reports = db.query(f"SELECT id, status, created_at FROM reports WHERE project_id = {db.ph} "
                       f"ORDER BY id DESC LIMIT 20", [pid])
    if not reports:
        st.info("暂无报告。")
        return
    rid = st.selectbox("选择报告", options=[r["id"] for r in reports],
                       format_func=lambda i: f"#{i} {next(r['created_at'] for r in reports if r['id'] == i)}")
    report = db.query_one(f"SELECT * FROM reports WHERE id = {db.ph}", [rid])
    st.markdown(report["content"])
    for fig in (report.get("figures") or [])[:12]:
        with st.expander(f"📊 {fig['title']}"):
            st.bar_chart(fig["data"])
    st.download_button("下载 Markdown", data=report["content"],
                       file_name=f"report_{rid}.md", mime="text/markdown")


if page.startswith("🚀"):
    render_auto()
elif page.startswith("⚙"):
    render_settings()
elif page.startswith("🕸"):
    render_graph()
elif page.startswith("🧪"):
    render_experiments()
elif page.startswith("📄"):
    render_report()
else:
    render_overview()
