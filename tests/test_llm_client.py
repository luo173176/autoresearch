from types import SimpleNamespace

from autoresearch.llm.client import LLMClient, verify_llm_connection


def test_cache_integration(test_settings, monkeypatch):
    calls = []

    def fake_call(self, messages, model, params):
        calls.append(messages[-1]["content"])
        return f"echo:{messages[-1]['content']}"

    monkeypatch.setattr(LLMClient, "_call_api", fake_call)
    client = LLMClient(test_settings)

    a = client.complete("hello")
    b = client.complete("hello")  # 第二次应命中缓存，不再调用 API
    c = client.complete("world")

    assert a == b == "echo:hello"
    assert c == "echo:world"
    assert calls == ["hello", "world"]
    assert client.cache.stats()["hits"] == 1


def test_batch_order_and_concurrency(test_settings, monkeypatch):
    monkeypatch.setattr(LLMClient, "_call_api", lambda self, m, model, p: m[-1]["content"])
    client = LLMClient(test_settings)
    prompts = [f"p{i}" for i in range(6)]
    out = client.batch_complete(prompts, max_concurrency=3)
    assert out == prompts  # 结果顺序与输入一致


def _fake_openai(content="OK", fail=False):
    class FakeCompletions:
        def create(self, **kwargs):
            if fail:
                raise RuntimeError("boom")
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

    return FakeOpenAI


def test_verify_connection_success(monkeypatch):
    import autoresearch.llm.client as client_mod

    monkeypatch.setattr(client_mod, "OpenAI", _fake_openai(content="OK"))
    ok, msg = verify_llm_connection("http://x/v1", "sk-test-123456789", "test-model")
    assert ok and "OK" in msg and "test-model" in msg


def test_verify_connection_failure(monkeypatch):
    import autoresearch.llm.client as client_mod

    monkeypatch.setattr(client_mod, "OpenAI", _fake_openai(fail=True))
    ok, msg = verify_llm_connection("http://x/v1", "bad-key", "m")
    assert not ok and "连接失败" in msg
