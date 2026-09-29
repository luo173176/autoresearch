"""端到端冒烟：真实 uvicorn（线程内）→ /health → 创建项目 → 查询项目。

用法: python tools/smoke.py
"""
import json
import os
import sys
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parents[1]
os.chdir(REPO)
os.environ.setdefault("AUTORESEARCH_SQLITE_PATH", str(REPO / "data" / "autoresearch.db"))
os.environ.setdefault("AUTORESEARCH_DATA_DIR", str(REPO / "data"))
os.environ.setdefault("AUTORESEARCH_LLM_CACHE_DIR", str(REPO / "data" / "cache" / "llm"))

import uvicorn  # noqa: E402

from autoresearch.api.main import create_app  # noqa: E402
from autoresearch.cli import run_init  # noqa: E402
from autoresearch.config import get_settings  # noqa: E402

PORT = 8123


def main() -> int:
    settings = get_settings()
    settings.ensure_dirs()
    run_init(settings)

    server = uvicorn.Server(
        uvicorn.Config(create_app(settings), host="127.0.0.1", port=PORT, log_level="warning")
    )
    threading.Thread(target=server.run, daemon=True).start()
    base = f"http://127.0.0.1:{PORT}"

    health = None
    for _ in range(50):
        try:
            with urlopen(base + "/health", timeout=2) as resp:
                health = json.loads(resp.read())
            break
        except Exception:
            time.sleep(0.2)
    if health is None:
        print("[smoke] 服务未就绪")
        return 1
    print("[smoke] /health ->", json.dumps(health, ensure_ascii=False))
    assert health["status"] == "ok" and health["database"] is True

    payload = json.dumps({
        "name": "smoke-project",
        "question": "Does reranking improve RAG QA accuracy?",
        "domain": "IR",
        "budget": {"gpu_hours": 1},
    }).encode()
    req = Request(base + "/projects", data=payload, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=5) as resp:
        created = json.loads(resp.read())
    print("[smoke] POST /projects ->", json.dumps(created, ensure_ascii=False))
    assert created["id"] > 0

    with urlopen(base + f"/projects/{created['id']}", timeout=5) as resp:
        got = json.loads(resp.read())
    assert got["name"] == "smoke-project"
    print(f"[smoke] GET /projects/{created['id']} -> ok")

    server.should_exit = True
    time.sleep(0.5)
    print("[smoke] 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
