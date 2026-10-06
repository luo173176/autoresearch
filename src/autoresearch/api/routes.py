"""API 路由：projects/literature/graph/hypotheses/experiments/reports 全链路真实实现。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from ..db import Database
from ..experiments import create_experiment, run_experiment
from ..graph import build_graph, export_graph
from ..hypotheses import generate_hypotheses
from ..literature import run_pipeline
from ..reporting import generate_report
from ..security import require_api_key, require_project_access
from ..schemas import (
    GraphBuildRequest,
    GraphBuildSummary,
    HypothesisGenerateRequest,
    HypothesisGenerateSummary,
    HypothesisOut,
    JobAccepted,
    JobOut,
    LiteratureRequest,
    LiteratureSummary,
    PaperOut,
    ProjectCreate,
    ProjectOut,
)

router = APIRouter(dependencies=[Depends(require_api_key), Depends(require_project_access)])


def _db(request: Request) -> Database:
    return request.app.state.db


def _submit_background(
    request: Request,
    *,
    job_type: str,
    project_id: int | None,
    payload: dict,
    fn,
    idempotency_key: str | None,
    response: Response | None = None,
) -> dict:
    if response is not None:
        response.status_code = 202
    jobs = request.app.state.jobs
    try:
        priority = int(
            request.headers.get("X-Job-Priority", request.app.state.settings.job_default_priority)
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="X-Job-Priority 必须是整数") from exc
    priority = max(0, min(priority, request.app.state.settings.job_max_priority))
    job, reused = jobs.create(
        _db(request),
        job_type=job_type,
        project_id=project_id,
        payload=payload,
        idempotency_key=idempotency_key,
        priority=priority,
    )
    if not reused or job["status"] == "queued":
        jobs.submit(_db(request), job, fn)
    return {
        "job_id": job["id"],
        "status": job["status"],
        "type": job_type,
        "poll_url": f"/jobs/{job['id']}",
    }


def _run_literature_job(db, settings, project, payload, update) -> dict:
    update(10, "searching")
    result = run_pipeline(
        db,
        settings,
        project=project,
        query=payload.query,
        sources=payload.sources,
        max_results=payload.max_results,
        download_pdfs=payload.download_pdfs,
        pdf_limit=payload.pdf_limit,
        use_llm=payload.use_llm,
    )
    update(100, "literature_completed")
    return result


def _run_graph_job(db, settings, project_id, payload, update) -> dict:
    update(10, "extracting_graph")
    result = build_graph(db, settings, project_id=project_id, use_llm=payload.use_llm)
    update(100, "graph_completed")
    return result


def _run_hypotheses_job(db, settings, project_id, payload, update) -> dict:
    update(10, "generating_hypotheses")
    result = generate_hypotheses(
        db,
        settings,
        project_id=project_id,
        max_hypotheses=payload.max_hypotheses,
        use_llm=payload.use_llm,
    )
    update(100, "hypotheses_completed")
    return result


def _run_experiment_job(db, settings, experiment_id, update) -> dict:
    update(10, "running_experiment")
    result = run_experiment(db, settings, experiment_id=experiment_id)
    update(100, "experiment_completed")
    return result


def _run_report_job(db, settings, project_id, update) -> dict:
    update(10, "generating_report")
    result = generate_report(db, settings, project_id=project_id)
    update(100, "report_completed")
    return result


def _handler_for_job(request: Request, job: dict):
    """从 jobs.input 重建可重试任务，避免把 Python 闭包持久化到数据库。"""
    from ..worker import handler_for_job

    try:
        return handler_for_job(_db(request), request.app.state.settings, job)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=f"任务类型或输入不支持重试: {exc}") from exc


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
    allowed = request.app.state.settings.api_key_project_id
    if allowed is not None:
        return db.query(
            f"SELECT * FROM projects WHERE id = {db.ph} ORDER BY id DESC LIMIT {db.ph}",
            [allowed, max(1, min(limit, 200))],
        )
    return db.query(
        f"SELECT * FROM projects ORDER BY id DESC LIMIT {db.ph}",
        [max(1, min(limit, 200))],
    )


@router.get("/projects/{project_id}", response_model=ProjectOut, tags=["projects"])
def get_project(project_id: int, request: Request) -> dict:
    db = _db(request)
    row = db.query_one(f"SELECT * FROM projects WHERE id = {db.ph}", [project_id])
    if row is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return row


# ---------- 文献（阶段 1） ----------
@router.post(
    "/projects/{project_id}/literature",
    response_model=LiteratureSummary | JobAccepted,
    tags=["literature"],
)
def run_literature(
    project_id: int,
    payload: LiteratureRequest,
    request: Request,
    background: bool = False,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    response: Response = None,
) -> dict:
    """检索文献 → 去重入库 → 项目关联 → 分块抽取（同步执行，耗时可传 download_pdfs=False 降低）。"""
    db = _db(request)
    project = db.query_one(f"SELECT * FROM projects WHERE id = {db.ph}", [project_id])
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    if background:
        return _submit_background(
            request,
            job_type="literature",
            project_id=project_id,
            payload={"project_id": project_id, **payload.model_dump()},
            idempotency_key=idempotency_key,
            response=response,
            fn=lambda job_db, update: _run_literature_job(
                job_db, request.app.state.settings, project, payload, update
            ),
        )
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


@router.get("/projects/{project_id}/papers", response_model=list[PaperOut], tags=["literature"])
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
@router.post(
    "/projects/{project_id}/graph", response_model=GraphBuildSummary | JobAccepted, tags=["graph"]
)
def build_project_graph(
    project_id: int,
    payload: GraphBuildRequest,
    request: Request,
    background: bool = False,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    response: Response = None,
) -> dict:
    """对项目已入库的 chunks 构建知识图谱（幂等，可重复执行）。"""
    db = _db(request)
    if db.query_one(f"SELECT id FROM projects WHERE id = {db.ph}", [project_id]) is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    if background:
        return _submit_background(
            request,
            job_type="graph",
            project_id=project_id,
            payload={"project_id": project_id, **payload.model_dump()},
            idempotency_key=idempotency_key,
            response=response,
            fn=lambda job_db, update: _run_graph_job(
                job_db, request.app.state.settings, project_id, payload, update
            ),
        )
    try:
        return build_graph(
            db, request.app.state.settings, project_id=project_id, use_llm=payload.use_llm
        )
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
@router.post(
    "/projects/{project_id}/hypotheses",
    response_model=HypothesisGenerateSummary | JobAccepted,
    tags=["hypotheses"],
)
def generate_project_hypotheses(
    project_id: int,
    payload: HypothesisGenerateRequest,
    request: Request,
    background: bool = False,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    response: Response = None,
) -> dict:
    """从项目图谱（矛盾/缺口/方法组合）生成假设并幂等入库。"""
    db = _db(request)
    if db.query_one(f"SELECT id FROM projects WHERE id = {db.ph}", [project_id]) is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    if background:
        return _submit_background(
            request,
            job_type="hypotheses",
            project_id=project_id,
            payload={"project_id": project_id, **payload.model_dump()},
            idempotency_key=idempotency_key,
            response=response,
            fn=lambda job_db, update: _run_hypotheses_job(
                job_db, request.app.state.settings, project_id, payload, update
            ),
        )
    try:
        return generate_hypotheses(
            db,
            request.app.state.settings,
            project_id=project_id,
            max_hypotheses=payload.max_hypotheses,
            use_llm=payload.use_llm,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get(
    "/projects/{project_id}/hypotheses", response_model=list[HypothesisOut], tags=["hypotheses"]
)
def list_project_hypotheses(project_id: int, request: Request, limit: int = 100) -> list[dict]:
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


@router.post(
    "/experiments/{experiment_id}/run", response_model=dict | JobAccepted, tags=["experiments"]
)
def run_experiment_endpoint(
    experiment_id: int,
    request: Request,
    background: bool = False,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    response: Response = None,
) -> dict:
    """执行实验（Docker 沙箱可用则沙箱执行，否则本地兜底；失败自动重试）。"""
    db = _db(request)
    exp = db.query_one(
        f"SELECT e.id, h.project_id FROM experiments e JOIN hypotheses h ON h.id = e.hypothesis_id "
        f"WHERE e.id = {db.ph}",
        [experiment_id],
    )
    if exp is None:
        raise HTTPException(status_code=404, detail="实验不存在")
    if background:
        return _submit_background(
            request,
            job_type="experiment_run",
            project_id=exp["project_id"],
            payload={"experiment_id": experiment_id},
            idempotency_key=idempotency_key,
            response=response,
            fn=lambda job_db, update: _run_experiment_job(
                job_db, request.app.state.settings, experiment_id, update
            ),
        )
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
        f"ORDER BY id DESC",
        [experiment_id],
    )
    return {"experiment": exp, "runs": runs}


# ---------- 报告（阶段 6） ----------
@router.post("/projects/{project_id}/report", response_model=dict | JobAccepted, tags=["reports"])
def create_report(
    project_id: int,
    request: Request,
    background: bool = False,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    response: Response = None,
) -> dict:
    """汇总项目全链路产出，生成带引用的论文初稿（幂等：每次生成新版本）。"""
    db = _db(request)
    if db.query_one(f"SELECT id FROM projects WHERE id = {db.ph}", [project_id]) is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    if background:
        return _submit_background(
            request,
            job_type="report",
            project_id=project_id,
            payload={"project_id": project_id},
            idempotency_key=idempotency_key,
            response=response,
            fn=lambda job_db, update: _run_report_job(
                job_db, request.app.state.settings, project_id, update
            ),
        )
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


# ---------- 后台任务（阶段 8） ----------
@router.get("/jobs", response_model=list[JobOut], tags=["jobs"])
def list_jobs(
    request: Request, project_id: int | None = None, status: str | None = None, limit: int = 50
) -> list[dict]:
    db = _db(request)
    limit = max(1, min(limit, 200))
    clauses: list[str] = []
    params: list = []
    if project_id is not None:
        clauses.append(f"project_id = {db.ph}")
        params.append(project_id)
    elif request.app.state.settings.api_key_project_id is not None:
        clauses.append(f"project_id = {db.ph}")
        params.append(request.app.state.settings.api_key_project_id)
    if status:
        clauses.append(f"status = {db.ph}")
        params.append(status)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    return db.query(f"SELECT * FROM jobs{where} ORDER BY id DESC LIMIT {db.ph}", params)


@router.get("/jobs/{job_id}", response_model=JobOut, tags=["jobs"])
def get_job(job_id: int, request: Request) -> dict:
    row = _db(request).query_one(f"SELECT * FROM jobs WHERE id = {_db(request).ph}", [job_id])
    if row is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return row


@router.post("/jobs/{job_id}/cancel", response_model=JobOut, tags=["jobs"])
def cancel_job(job_id: int, request: Request) -> dict:
    db = _db(request)
    row = request.app.state.jobs.cancel(db, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if row["status"] == "running":
        raise HTTPException(status_code=409, detail="任务已开始运行，只能等待其完成")
    return row


@router.post("/jobs/{job_id}/retry", response_model=JobOut, tags=["jobs"])
def retry_job(job_id: int, request: Request) -> dict:
    db = _db(request)
    job = db.query_one(f"SELECT * FROM jobs WHERE id = {db.ph}", [job_id])
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job["status"] not in {"failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="只有 failed 或 cancelled 任务可以重试")
    fn = _handler_for_job(request, job)
    queued = request.app.state.jobs.reset_for_retry(db, job_id)
    request.app.state.jobs.submit(db, queued, fn)
    return db.query_one(f"SELECT * FROM jobs WHERE id = {db.ph}", [job_id])
