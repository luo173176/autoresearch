from autoresearch.cli import main, run_config, run_init


def test_version(capsys):
    assert main(["version"]) == 0
    assert "AutoResearch" in capsys.readouterr().out


def test_init_idempotent(test_settings, capsys):
    assert run_init(test_settings) == 0
    out = capsys.readouterr().out
    assert "sqlite" in out
    assert (test_settings.data_dir / "papers").is_dir()
    assert test_settings.sqlite_path.exists()
    # 幂等：重复 init 不报错、迁移不再执行
    assert run_init(test_settings) == 0
    assert "已是最新" in capsys.readouterr().out


def test_config_show_masks_key(test_settings, capsys, monkeypatch):
    monkeypatch.chdir(test_settings.data_dir.parent)  # 任意目录均可展示
    s = test_settings.model_copy(update={"llm_api_key": "sk-very-secret-123456789"})
    assert run_config(test=False, settings=s) == 0
    out = capsys.readouterr().out
    assert s.llm_base_url in out
    assert "sk-very-secret" not in out  # 打码
    assert "****" in out


def test_config_test_flag(test_settings, capsys, monkeypatch):
    # run_config 在调用时才 import verify_llm_connection，monkeypatch 源头即可生效
    monkeypatch.setattr(
        "autoresearch.llm.client.verify_llm_connection",
        lambda *a, **k: (True, "连接成功（1ms）：回复 OK"),
    )
    assert run_config(test=True, settings=test_settings) == 0
    assert "[OK]" in capsys.readouterr().out
