from autoresearch.config import Settings


def test_defaults(test_settings):
    assert test_settings.database_url == ""
    assert test_settings.llm_model
    assert test_settings.prompt_version == "v0"
    assert test_settings.llm_base_url.startswith("http")


def test_env_override(test_settings, monkeypatch):
    monkeypatch.setenv("AUTORESEARCH_LLM_MODEL", "my-model")
    monkeypatch.setenv("AUTORESEARCH_API_PORT", "9")
    s = Settings(_env_file=None)
    assert s.llm_model == "my-model"
    assert s.api_port == 9


def test_ensure_dirs(test_settings):
    test_settings.ensure_dirs()
    for sub in ("papers", "cache", "artifacts", "experiments"):
        assert (test_settings.data_dir / sub).is_dir()
    assert test_settings.llm_cache_dir.is_dir()


def test_save_env_values_roundtrip(tmp_path):
    from autoresearch.config import save_env_values

    env = tmp_path / ".env"
    env.write_text(
        "# my comment\nAUTORESEARCH_LLM_MODEL=old-model\nAUTORESEARCH_API_PORT=8000\n",
        encoding="utf-8",
    )
    save_env_values({
        "AUTORESEARCH_LLM_MODEL": "new-model",
        "AUTORESEARCH_LLM_API_KEY": "sk-test-123456789",
        "AUTORESEARCH_LLM_ENABLED": "false",
    }, env_path=env)
    text = env.read_text(encoding="utf-8")
    assert "AUTORESEARCH_LLM_MODEL=new-model" in text  # 已有键被原位更新
    assert "AUTORESEARCH_API_PORT=8000" in text  # 未涉及行保留
    assert "AUTORESEARCH_LLM_API_KEY=sk-test-123456789" in text  # 新键追加
    assert "AUTORESEARCH_LLM_ENABLED=false" in text
    assert text.splitlines()[0].startswith("#")
    # pydantic-settings 能从该文件读取
    s = Settings(_env_file=str(env))
    assert s.llm_model == "new-model" and s.llm_api_key == "sk-test-123456789"
    assert s.llm_enabled is False


def test_save_env_values_creates_file(tmp_path):
    from autoresearch.config import save_env_values

    env = tmp_path / "sub" / ".env"
    save_env_values({"AUTORESEARCH_LLM_BASE_URL": "http://x/v1"}, env_path=env)
    assert "AUTORESEARCH_LLM_BASE_URL=http://x/v1" in env.read_text(encoding="utf-8")
