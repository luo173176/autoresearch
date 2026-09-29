from autoresearch.sandbox.docker_runner import is_docker_available


def test_ui_module_imports():
    import autoresearch.ui.app as app_mod  # noqa: F401  Streamlit 裸模式仅告警


def test_docker_availability_probe():
    # 环境无关：只验证探测函数可调用且返回布尔值（Docker 未装时为 False）
    assert isinstance(is_docker_available(), bool)
