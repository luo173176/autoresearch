"""pytest 公共夹具：隔离环境变量，所有资源落在 tmp_path。"""

import os

import pytest

from autoresearch.config import Settings


@pytest.fixture()
def test_settings(tmp_path, monkeypatch):
    for var in [v for v in os.environ if v.startswith("AUTORESEARCH_")]:
        monkeypatch.delenv(var, raising=False)
    return Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        sqlite_path=tmp_path / "data" / "test.db",
        llm_cache_dir=tmp_path / "data" / "cache" / "llm",
        llm_enabled=False,  # 测试确定性：LLM 相关路径单独用假对象覆盖
        execution_mode="unsafe-local",  # 测试只运行仓库自生成的受控实验包
    )


@pytest.fixture()
def db(test_settings):
    from autoresearch.db import Database

    database = Database(test_settings)
    database.migrate()
    return database
