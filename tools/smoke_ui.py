"""Streamlit 冒烟：以子进程启动 headless Streamlit，验证 HTTP 200 后退出。

用法: python tools/smoke_ui.py
"""
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

REPO = Path(__file__).resolve().parents[1]
os.chdir(REPO)
env = os.environ.copy()
env.setdefault("AUTORESEARCH_SQLITE_PATH", str(REPO / "data" / "autoresearch.db"))
PORT = 8599


def main() -> int:
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run",
            str(REPO / "src" / "autoresearch" / "ui" / "app.py"),
            "--server.port", str(PORT),
            "--server.headless", "true",
            "--browser.gatherUsageStats", "false",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    ok = False
    try:
        for _ in range(120):
            if proc.poll() is not None:
                break
            try:
                with urlopen(f"http://127.0.0.1:{PORT}/", timeout=2) as resp:
                    if resp.status == 200:
                        ok = True
                        break
            except Exception:
                time.sleep(0.3)
        time.sleep(3)  # 给页面脚本执行留出时间，若崩溃进程会退出
        crashed = proc.poll() is not None
        print(f"[smoke-ui] HTTP 200: {ok} | 进程存活: {not crashed}")
        ok = ok and not crashed
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    print("[smoke-ui] 通过" if ok else "[smoke-ui] 失败")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
