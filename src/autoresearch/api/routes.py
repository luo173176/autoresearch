"""API 路由：projects/literature/graph/hypotheses/experiments/reports 全链路真实实现。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..db import Database
from ..experiments import create_experiment, run_experiment
from ..graph import build_graph, export_graph
from ..hypotheses import generate_hypotheses
from ..literature import run_pipeline
from ..reporting import generate_report
from ..schemas import (
    GraphBuildRequest,
    GraphBuildSummary,
    HypothesisGenerateRequest,
    HypothesisGenerateSummary,
    HypothesisOut,
    LiteratureRequest,
    LiteratureSummary,
    PaperOut,
    ProjectCreate,
    ProjectOut,
)

router = APIRouter()


def _db(request: Request) -> Database:
    return request.app.state.db


# ---------- 项目 ----------
@router.post("/projects", response_model=ProjectOut, status_code=201, tags=["projects"])
def create_project(payload: ProjectCreate, request: Request) -> dict:
    db = _db(request)
    pid = db.insert(
        f"INSERT INTO projects (name, question, domain, budget) "
        f"VALUES ({db.ph}, {db.ph}, {db.ph}, {db.ph})",
        [payload.name, payload.question, payload.domain, db.dumps(payload.budget)],
    )
    return db.query_one(f"SELECT * FROM projects WHERE id = {db.ph}", [pid])


@router.get("/projects", response_model=list[ProjectOut], tags=["projects"])
def list_projects(request: Request, limit: int = 50) -> list[dict]:
    db = _db(request)
    return db.query(f"SELECT * FROM projects ORDER BY id DESC LIMIT {db.ph}", [limit])


@router.get("/projects/{project_id}", response_model=ProjectOut, tags=["projects"])
def get_project(project_id: int, request: Request) -> dict:
    db = _db(request)
    row = db.query_one(f"SELECT * FROM projects WHERE id = {db.ph}", [project_id])
    if row is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return row


# ---------- 文献（阶段 1） ----------
@router.post("/projects/{project_id}/literature", response_model=LiteratureSummary,
             tags=["literature"])
def run_literature(project_id: int, payload: LiteratureRequest, request: Request) -> dict:
    """检索文献 → 去重入库 → 项目关联 → 分块抽取（同步执行，耗时可传 download_pdfs=False 降低）。"""
    db = _db(request)
    project = db.query_one(f"SELECT * FROM projects WHERE id = {db.ph}", [project_id])
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return run_pipeline(
        db,
        request.app.state.settings,
        project=project,
        query=payload.query,
        sources=payload.sources,
        max_results=payload.max_results,
        download_pdfs=payload.download_pdfs,
        pdf_limit=payload.pdf_limit,
        use_llm=payload.use_llm,
    )


@router.get("/projects/{project_id}/papers", response_model=list[PaperOut],
            tags=["literature"])
def list_project_papers(project_id: int, request: Request) -> list[dict]:
    db = _db(request)
    if db.query_one(f"SELECT id FROM projects WHERE id = {db.ph}", [project_id]) is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return db.query(
        f"SELECT p.* FROM papers p JOIN projects_papers pp ON pp.paper_id = p.id "
        f"WHERE pp.project_id = {db.ph} ORDER BY pp.id DESC LIMIT 500",
        [project_id],
    )


# ---------- 知识图谱（阶段 2） ----------
@router.post("/projects/{project_id}/graph", response_model=GraphBuildSummary,
             tags=["graph"])
def build_project_graph(project_id: int, payload: GraphBuildRequest, request: Request) -> dict:
    """对项目已入库的 chunks 构建知识图谱（幂等，可重复执行）。"""
    db = _db(request)
    if db.query_one(f"SELECT id FROM projects WHERE id = {db.ph}", [project_id]) is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    try:
        return build_graph(db, request.app.state.settings, project_id=project_id,
                           use_llm=payload.use_llm)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/projects/{project_id}/graph", tags=["graph"])
def get_project_graph(project_id: int, request: Request) -> dict:
    """导出项目子图 {nodes, links}，可直接喂给可视化组件。"""
    db = _db(request)
    if db.query_one(f"SELECT id FROM projects WHERE id = {db.ph}", [project_id]) is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return export_graph(db, project_id)


# ---------- 假设生成（阶段 3） ----------
@router.post("/projects/{project_id}/hypotheses", response_model=HypothesisGenerateSummary,
             tags=["hypotheses"])
def generate_project_hypotheses(project_id: int, payload: HypothesisGenerateRequest,
                                request: Request) -> dict:
    """从项目图谱（矛盾/缺口/方法组合）生成假设并幂等入库。"""
    db = _db(request)
    if db.query_one(f"SELECT id FROM projects WHERE id = {db.ph}", [project_id]) is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    try:
        return generate_hypotheses(db, request.app.state.settings, project_id=project_id,
                                   max_hypotheses=payload.max_hypotheses,
                                   use_llm=payload.use_llm)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/projects/{project_id}/hypotheses", response_model=list[HypothesisOut],
            tags=["hypotheses"])
def list_project_hypotheses(project_id: int, request: Request,
                            limit: int = 100) -> list[dict]:
    db = _db(request)
    if db.query_one(f"SELECT id FROM projects WHERE id = {db.ph}", [project_id]) is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return db.query(
        f"SELECT * FROM hypotheses WHERE project_id = {db.ph} ORDER BY novelty DESC, id LIMIT {int(limit)}",
        [project_id],
    )


# ---------- 实验与执行（阶段 4/5） ----------
@router.post("/hypotheses/{hypothesis_id}/experiments", status_code=201, tags=["experiments"])
def design_experiment(hypothesis_id: int, request: Request) -> dict:
    """由假设生成实验设计 + 可运行代码包（独立工作区）。"""
    db = _db(request)
    try:
        return create_experiment(db, request.app.state.settings, hypothesis_id=hypothesis_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/experiments/{experiment_id}/run", tags=["experiments"])
def run_experiment_endpoint(experiment_id: int, request: Request) -> dict:
    """执行实验（Docker 沙箱可用则沙箱执行，否则本地兜底；失败自动重试）。"""
    db = _db(request)
    try:
        return run_experiment(db, request.app.state.settings, experiment_id=experiment_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/experiments/{experiment_id}", tags=["experiments"])
def get_experiment(experiment_id: int, request: Request) -> dict:
    db = _db(request)
    exp = db.query_one(f"SELECT * FROM experiments WHERE id = {db.ph}", [experiment_id])
    if exp is None:
        raise HTTPException(status_code=404, detail="实验不存在")
    runs = db.query(
        f"SELECT id, status, config, metrics, logs FROM runs WHERE experiment_id = {db.ph} "
        f"ORDER BY id DESC", [experiment_id],
    )
    return {"experiment": exp, "runs": runs}


# ---------- 报告（阶段 6） ----------
@router.post("/projects/{project_id}/report", tags=["reports"])
def create_report(project_id: int, request: Request) -> dict:
    """汇总项目全链路产出，生成带引用的论文初稿（幂等：每次生成新版本）。"""
    db = _db(request)
    try:
        return generate_report(db, request.app.state.settings, project_id=project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/reports/{report_id}", tags=["reports"])
def get_report(report_id: int, request: Request) -> dict:
    db = _db(request)
    row = db.query_one(f"SELECT * FROM reports WHERE id = {db.ph}", [report_id])
    if row is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    return row
