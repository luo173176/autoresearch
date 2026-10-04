# 贡献指南

## 开发环境

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
cp .env.example .env
```

Windows 使用 `.venv\\Scripts\\python` 和 `.venv\\Scripts\\autoresearch`。

## 提交前检查

```bash
ruff check .
ruff format --check .
pytest
```

如果修改了 Docker、迁移或执行器，请额外运行：

```bash
docker build -t autoresearch:local .
docker compose config
```

## 代码要求

- 新功能必须有测试。
- 修改数据库结构必须同时提交 SQLite 和 PostgreSQL 迁移。
- 修改提示词必须递增 `AUTORESEARCH_PROMPT_VERSION`。
- 不要提交 `.env`、API key、论文缓存、实验产物或数据库文件。
- 生产执行模式保持 `strict`，本地执行必须在测试或开发配置中显式声明。
- API 错误应返回可理解的 HTTP 状态和中文/英文均可读的错误信息。

## Pull Request

PR 描述请包含：

1. 修改目标
2. 设计取舍
3. 测试命令和结果
4. 是否包含迁移
5. 是否改变默认安全行为
6. README 或 DECISIONS.md 是否需要更新
