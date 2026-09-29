"""Docker 沙箱执行器：资源限制、隔离文件系统、失败可重试（由 experiments.runner 调用）。

无 Docker 环境时 experiments.runner 自动降级为本地子进程执行（run 元数据记录 executor）。
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from loguru import logger

from ..config import Settings


class SandboxUnavailable(RuntimeError):
    pass


def is_docker_available() -> bool:
    """检测 Docker 守护进程是否可用。"""
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "ok"],
            capture_output=True, text=True, timeout=15,
        )
        return result.returncode == 0
    except Exception as exc:
        logger.debug("docker info 失败: {}", exc)
        return False


def run_sandboxed(workspace: Path | str, settings: Settings, *, cpus: float = 1.0,
                  memory: str = "1g", image: str = "python:3.12-slim",
                  timeout: float | None = None) -> dict:
    """在 Docker 容器中运行实验工作区（CPU/内存限制、只读依赖安装）。

    返回 {exit_code, stdout, stderr}；Docker 不可用抛 SandboxUnavailable。
    """
    if not is_docker_available():
        raise SandboxUnavailable("Docker 不可用：请安装/启动 Docker，或使用本地执行器兜底")
    workspace = Path(workspace).resolve()
    cmd = [
        "docker", "run", "--rm",
        "--cpus", str(cpus), "--memory", memory,
        "-v", f"{workspace}:/work", "-w", "/work",
        image,
        "sh", "-c",
        "pip install --no-cache-dir -q -r requirements.txt "
        "&& python main.py --config config.json --output results.json",
    ]
    logger.info("沙箱执行: {} (cpus={}, memory={})", workspace, cpus, memory)
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout or settings.experiment_timeout)
    return {"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
