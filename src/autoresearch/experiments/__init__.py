"""实验编排：创建（设计+代码生成）、执行（Docker 沙箱/本地兜底）、分析。"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from loguru import logger

from ..config import Settings, get_settings
from ..sandbox.docker_runner import is_docker_available, run_sandboxed
from .analyzer import analyze_results
from .codegen import generate_experiment_code
from .designer import design_from_hypothesis

__all__ = ["create_experiment", "run_experiment", "analyze_results"]


def create_experiment(db, settings: Settings | None = None, *, hypothesis_id: int) -> dict:
    """由假设生成实验设计 + 代码包（独立工作区 data/experiments/{id}/）。"""
    settings = settings or get_settings()
    settings.ensure_dirs()
    hyp = db.query_one(f"SELECT * FROM hypotheses WHERE id = {db.ph}", [hypothesis_id])
    if hyp is None:
        raise LookupError(f"假设 #{hypothesis_id} 不存在")

    design = design_from_hypothesis(hyp, settings)
    eid = db.insert(
        f"INSERT INTO experiments (hypothesis_id, design, datasets, baselines, metrics, status) "
        f"VALUES ({db.ph}, {db.ph}, {db.ph}, {db.ph}, {db.ph}, {db.ph})",
        [hypothesis_id, db.dumps(design), db.dumps(design["datasets"]),
         db.dumps([b["name"] for b in design["baselines"]]), db.dumps(design["metrics"]),
         "designed"],
    )
    workspace = Path(settings.data_dir) / "experiments" / str(eid)
    files = generate_experiment_code(workspace, design, eid)
    logger.info("实验 #{} 已生成: {} ({} 个文件)", eid, workspace, len(files))
    return {"experiment_id": eid, "workspace": str(workspace), "files": files, "design": design}


def _execute_local(workspace: Path, settings: Settings) -> dict:
    proc = subprocess.run(
        [sys.executable, "main.py", "--config", "config.json", "--output", "results.json"],
        cwd=workspace, capture_output=True, text=True,
        timeout=settings.experiment_timeout, encoding="utf-8", errors="replace",
    )
    return {"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def run_experiment(db, settings: Settings | None = None, *, experiment_id: int,
                   attempts: int = 2) -> dict:
    """执行实验：执行计划 docker → local 逐级降级；失败重试。

    Docker 可用但镜像拉取失败（如 registry 不可达）时，自动回退本地执行器。
    """
    settings = settings or get_settings()
    exp = db.query_one(f"SELECT * FROM experiments WHERE id = {db.ph}", [experiment_id])
    if exp is None:
        raise LookupError(f"实验 #{experiment_id} 不存在")
    # 工作区路径是确定性的：data/experiments/{experiment_id}/（code_path 记录在 runs 行）
    workspace = Path(settings.data_dir) / "experiments" / str(experiment_id)
    if not (workspace / "main.py").exists():
        raise LookupError(f"实验 #{experiment_id} 缺少代码包: {workspace}")

    use_docker = settings.sandbox_enabled and is_docker_available()
    plan: list[str] = []
    if use_docker:
        plan.append("docker")
    plan.extend(["local"] * max(attempts - len(plan), 1))
    plan = plan[:attempts]

    run_id = db.insert(
        f"INSERT INTO runs (experiment_id, code_path, config, status) "
        f"VALUES ({db.ph}, {db.ph}, {db.ph}, {db.ph})",
        [experiment_id, str(workspace),
         db.dumps({"executor_plan": plan}), "running"],
    )

    last_error = ""
    for attempt, executor in enumerate(plan, 1):
        started = time.perf_counter()
        try:
            if executor == "docker":
                proc = run_sandboxed(workspace, settings,
                                     cpus=settings.sandbox_cpus,
                                     memory=settings.sandbox_memory,
                                     image=settings.sandbox_image,
                                     timeout=settings.experiment_timeout)
                ok = proc["exit_code"] == 0
                logs = proc["stdout"] + "\n[stderr]\n" + proc["stderr"]
            else:
                proc = _execute_local(workspace, settings)
                ok = proc["exit_code"] == 0
                logs = proc["stdout"] + "\n[stderr]\n" + proc["stderr"]

            if ok:
                results = json.loads((workspace / "results.json").read_text(encoding="utf-8"))
                analysis = analyze_results(results)
                db.execute(
                    f"UPDATE runs SET status = {db.ph}, metrics = {db.ph}, logs = {db.ph} "
                    f"WHERE id = {db.ph}",
                    ["completed",
                     db.dumps({"executor": executor, "attempts_used": attempt,
                               "elapsed_ms": int((time.perf_counter() - started) * 1000),
                               "results": results.get("runs", []), "analysis": analysis}),
                     logs[-20000:], run_id],
                )
                logger.info("实验 #{} run#{} 完成 ({})", experiment_id, run_id, executor)
                return {"run_id": run_id, "status": "completed", "executor": executor,
                        "attempt": attempt, "analysis": analysis}
            last_error = logs[-2000:]
        except Exception as exc:  # 超时/环境错误均计为失败尝试
            last_error = f"{type(exc).__name__}: {exc}"
        logger.warning("实验 #{} run#{} 第 {} 次尝试({})失败: {}",
                       experiment_id, run_id, attempt, executor, last_error[:200])

    db.execute(f"UPDATE runs SET status = {db.ph}, logs = {db.ph} WHERE id = {db.ph}",
               ["failed", f"plan={plan}\nlast_error={last_error}", run_id])
    return {"run_id": run_id, "status": "failed", "error": last_error}
