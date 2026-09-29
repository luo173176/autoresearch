from autoresearch.llm.cache import LLMCache

MSGS = [{"role": "user", "content": "你好"}]


def test_key_stability(tmp_path):
    c1 = LLMCache(tmp_path / "c1", "v1")
    c2 = LLMCache(tmp_path / "c2", "v1")
    # 相同输入 → 相同 key（跨实例稳定，支持断点续跑）
    assert c1.key(model="m", messages=MSGS) == c2.key(model="m", messages=MSGS)
    # 模型不同 → key 不同
    assert c1.key(model="m", messages=MSGS) != c1.key(model="m2", messages=MSGS)
    # 消息不同 → key 不同
    assert c1.key(model="m", messages=MSGS) != c1.key(
        model="m", messages=MSGS + [{"role": "user", "content": "x"}]
    )
    # prompt_version 参与 key（改提示词必须升版本）
    c3 = LLMCache(tmp_path / "c3", "v2")
    assert c1.key(model="m", messages=MSGS) != c3.key(model="m", messages=MSGS)
    # 参数不同 → key 不同
    assert c1.key(model="m", messages=MSGS) != c1.key(model="m", messages=MSGS, params={"t": 0})


def test_roundtrip_and_stats(tmp_path):
    cache = LLMCache(tmp_path, "v1")
    key = cache.key(model="m", messages=MSGS)
    assert cache.get(key) is None
    cache.put(key, {"answer": 42})
    assert cache.get(key) == {"answer": 42}
    assert cache.stats()["misses"] == 1
    assert cache.stats()["hits"] == 1


def test_disabled(tmp_path):
    cache = LLMCache(tmp_path, "v1", enabled=False)
    key = cache.key(model="m", messages=MSGS)
    cache.put(key, "x")
    assert cache.get(key) is None
