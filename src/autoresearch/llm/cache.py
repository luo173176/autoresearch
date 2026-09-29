"""LLM 结果缓存：key = sha256(prompt_version + model + messages + params)。

结果以 JSON 文件落盘（data/cache/llm），天然持久化：
- 约束「缓存 key = hash(prompt + prompt_version)」的超集（叠加 model/params，防止换模型后串答案）
- 断点续跑：批处理任务重跑时，已完成的 prompt 直接命中缓存，不再消耗 token
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


class LLMCache:
    def __init__(self, cache_dir: Path | str, prompt_version: str = "v0", enabled: bool = True):
        self.cache_dir = Path(cache_dir)
        self.prompt_version = prompt_version
        self.enabled = enabled
        self.hits = 0
        self.misses = 0
        if enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def key(self, *, model: str, messages: list[dict], params: dict | None = None) -> str:
        payload = {
            "prompt_version": self.prompt_version,
            "model": model,
            "messages": messages,
            "params": params or {},
        }
        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        return self.cache_dir / key[:2] / f"{key}.json"

    def get(self, key: str) -> Any | None:
        if not self.enabled:
            return None
        path = self._path(key)
        if path.exists():
            try:
                self.hits += 1
                return json.loads(path.read_text(encoding="utf-8"))["result"]
            except (OSError, ValueError, KeyError):
                self.misses += 1
                return None
        self.misses += 1
        return None

    def put(self, key: str, result: Any) -> None:
        if not self.enabled:
            return
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"result": result, "cached_at": time.time()}, ensure_ascii=False),
            encoding="utf-8",
        )

    def stats(self) -> dict:
        return {"hits": self.hits, "misses": self.misses, "dir": str(self.cache_dir)}
