"""OpenAI-compatible LLM 客户端：批处理 + 缓存 + 重试，本地优先（默认 Ollama）。

通过 base_url/api_key/model 配置即可切换 Ollama / DeepSeek / OpenAI，无需改代码。
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from loguru import logger
from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import Settings, get_settings
from .cache import LLMCache

_RETRY_ERRORS = (APITimeoutError, APIConnectionError, RateLimitError, InternalServerError)


def verify_llm_connection(base_url: str, api_key: str, model: str,
                        timeout: float = 20.0) -> tuple[bool, str]:
    """真实发送一条最小对话，验证 base_url/api_key/model 三要素。返回 (是否成功, 消息)。"""
    try:
        client = OpenAI(base_url=base_url.strip(), api_key=api_key.strip() or "local",
                        timeout=timeout)
        started = time.perf_counter()
        resp = client.chat.completions.create(
            model=model.strip(),
            messages=[{"role": "user", "content": "请只回复两个字母：OK"}],
            max_tokens=16,
            temperature=0.0,
        )
        text = (resp.choices[0].message.content or "").strip()
        elapsed = int((time.perf_counter() - started) * 1000)
        return True, f"连接成功（{elapsed}ms）：模型「{model.strip()}」回复「{text[:40]}」"
    except Exception as exc:
        return False, f"连接失败：{type(exc).__name__}: {str(exc)[:200]}"


class LLMClient:
    def __init__(self, settings: Settings | None = None, cache: LLMCache | None = None):
        self.settings = settings or get_settings()
        s = self.settings
        self.cache = cache or LLMCache(s.llm_cache_dir, s.prompt_version)
        self._client = OpenAI(
            base_url=s.llm_base_url,
            api_key=s.llm_api_key or "local",
            timeout=s.llm_timeout,
        )

    def chat(
        self, messages: list[dict], *, model: str | None = None, use_cache: bool = True, **params: Any
    ) -> str:
        model = model or self.settings.llm_model
        params.setdefault("temperature", self.settings.llm_temperature)
        key = self.cache.key(model=model, messages=messages, params=params)
        if use_cache and (hit := self.cache.get(key)) is not None:
            return hit
        text = self._call_api(messages, model, params)
        if use_cache:
            self.cache.put(key, text)
        return text

    @retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type(_RETRY_ERRORS),
    )
    def _call_api(self, messages: list[dict], model: str, params: dict) -> str:
        resp = self._client.chat.completions.create(model=model, messages=messages, **params)
        return (resp.choices[0].message.content or "").strip()

    def complete(self, prompt: str, system: str | None = None, **kwargs: Any) -> str:
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}
        ]
        return self.chat(messages, **kwargs)

    def batch_complete(
        self, prompts: list[str], *, system: str | None = None, max_concurrency: int | None = None, **kwargs: Any
    ) -> list[str]:
        """批处理：并发执行，结果顺序与输入一致；命中缓存的 prompt 不消耗 API。"""
        workers = max_concurrency or self.settings.llm_max_concurrency
        results: list[str | None] = [None] * len(prompts)

        def work(i: int, prompt: str) -> None:
            results[i] = self.complete(prompt, system=system, **kwargs)

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(work, i, p): i for i, p in enumerate(prompts)}
            for future in as_completed(futures):
                future.result()  # 任一失败立即抛出
        logger.info("batch_complete 完成 {} 条，缓存命中 {}", len(prompts), self.cache.hits)
        return [r or "" for r in results]
