# AutoResearch

自主科研与实验平台：把一个研究问题推进为**文献检索 → 知识图谱 → 研究假设 → 实验包 → 受限执行 → 结果分析 → 带引用报告**。

> 当前版本：`0.2.0`。项目适合个人研究、原型验证和可复现实验流程探索。规则抽取与代理实验不能替代领域专家审核或真实论文复现。

## 你可以用它做什么

| 能力 | 说明 |
|---|---|
| 文献检索 | 支持 arXiv、Semantic Scholar、PubMed，以及本地 PDF 解析 |
| 知识图谱 | 从论文中抽取方法、数据集、指标、结论、缺口和矛盾 |
| 假设生成 | 基于证据生成可验证、可追溯的研究假设 |
| 实验设计 | 将假设转换为独立实验工作区和可运行代码包 |
| 受限执行 | 默认要求 Docker 沙箱，限制 CPU、内存、网络和进程数 |
| 报告产出 | 生成带论文引用、实验结果和局限性说明的 Markdown 报告 |
| 离线兜底 | 没有 LLM 时使用规则抽取；没有外部数据库时使用 SQLite |

## 先看安全说明

实验代码属于潜在不可信代码。**生产默认是严格沙箱模式**：Docker 不可用时拒绝执行，不会静默在宿主机运行。

```env
AUTORESEARCH_EXECUTION_MODE=strict
AUTORESEARCH_ALLOW_NETWORK=false
```

本地开发、且确认实验工作区可信时，才显式使用：

```env
AUTORESEARCH_EXECUTION_MODE=safe-local
```

`unsafe-local` 仅用于完全受信任的开发调试，不建议在生产或处理用户提交代码时使用。详见 [SECURITY.md](SECURITY.md)。

## 10 分钟启动

### 1. 安装

要求 Python 3.11–3.13。推荐使用虚拟环境：

```bash
python -m venv .venv

# Linux/macOS
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install -e . --no-deps

# Windows PowerShell
.venv\Scripts\python -m pip install -r requirements.lock
.venv\Scripts\python -m pip install -e . --no-deps
```

开发依赖安装方式：

```bash
python -m pip install -e ".[dev]"
```

### 2. 配置

```bash
# Linux/macOS
cp .env.example .env

# Windows
copy .env.example .env
```

默认配置：

- SQLite：`data/autoresearch.db`
- LLM：本机 Ollama，可选
- Docker 执行模式：`strict`
- Docker 实验网络：关闭
- 数据和缓存：`data/`

没有 LLM 也可以运行文献解析、规则图谱和基础实验流程。若要使用 LLM 增强，请编辑 `.env` 中的 `AUTORESEARCH_LLM_*` 配置。

### 3. 初始化并启动

```bash
.venv/bin/autoresearch init
.venv/bin/autoresearch serve
```

另开终端启动看板：

```bash
.venv/bin/autoresearch ui
```

访问：

- API 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/health>
- Streamlit 看板：<http://127.0.0.1:8501>

Windows 将 `.venv/bin/autoresearch` 替换为 `.venv\Scripts\autoresearch`。

## 一键跑通

### 命令行

```bash
# 只使用规则路径，适合离线验证
.venv/bin/autoresearch literature "retrieval augmented generation" --max 10 --sources arxiv --no-llm
.venv/bin/autoresearch graph --no-llm
.venv/bin/autoresearch hypotheses --no-llm
.venv/bin/autoresearch experiment

# 严格模式下需要 Docker 才会执行实验
.venv/bin/autoresearch run 1
.venv/bin/autoresearch report --export data/artifacts/report.md
```

### 看板

启动 UI 后进入 **“一键研究”** 页面，输入研究问题并开始流程。首次使用建议先在 **“设置”** 页面配置 LLM，并用“测试连接”验证。

### Docker Compose

需要安装 Docker：

```bash
docker compose up -d --build
```

服务地址：API `http://localhost:8000`，UI `http://localhost:8501`，PostgreSQL `localhost:5432`。

## 命令一览

| 命令 | 用途 |
|---|---|
| `autoresearch init` | 创建数据目录并执行迁移 |
| `autoresearch serve` | 启动 FastAPI |
| `autoresearch ui` | 启动 Streamlit 看板 |
| `autoresearch literature "问题"` | 检索、去重、入库和分块 |
| `autoresearch graph` | 构建知识图谱 |
| `autoresearch hypotheses` | 生成研究假设 |
| `autoresearch experiment` | 设计实验并生成实验包 |
| `autoresearch run <id>` | 按安全策略执行实验 |
| `autoresearch report` | 生成带引用报告 |
| `autoresearch watch` | 定时扫描新论文并刷新产物 |
| `autoresearch eval` | 运行评估集 |
| `autoresearch config --test` | 检查 LLM 配置和连接 |

## 关键配置

所有变量使用 `AUTORESEARCH_` 前缀，完整示例见 [.env.example](.env.example)。

### 执行安全

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `EXECUTION_MODE` | `strict` | `strict`、`safe-local` 或 `unsafe-local` |
| `SANDBOX_ENABLED` | `true` | 是否尝试 Docker |
| `ALLOW_NETWORK` | `false` | Docker 实验是否允许网络 |
| `MAX_OUTPUT_BYTES` | `200000` | 单次 stdout/stderr 最大保存量 |
| `API_KEY` | 空 | 非空时要求 `X-API-Key` 或 `Authorization: Bearer ...` |
| `JOB_MAX_WORKERS` | `2` | 进程内后台任务并发数 |
| `JOB_MAX_ATTEMPTS` | `3` | 任务执行尝试上限 |
| `JOB_RETRY_BACKOFF_SECONDS` | `0.2` | 自动重试指数退避初始秒数 |
| `JOB_STALE_AFTER_SECONDS` | `300` | 任务心跳告警阈值 |
| `SANDBOX_CPUS` | `1.0` | Docker CPU 限制 |
| `SANDBOX_MEMORY` | `1g` | Docker 内存限制 |
| `SANDBOX_IMAGE` | `python:3.12-slim` | 实验沙箱镜像 |

### 数据库

| 变量 | 说明 |
|---|---|
| `DATABASE_URL` | PostgreSQL DSN；为空时使用 SQLite |
| `SQLITE_PATH` | SQLite 文件路径 |
| `DATA_DIR` | 论文、缓存、报告和实验工作区根目录 |

### LLM

| 变量 | 说明 |
|---|---|
| `LLM_BASE_URL` | OpenAI-compatible API 地址 |
| `LLM_API_KEY` | API key；本地 Ollama 通常填写 `ollama` |
| `LLM_MODEL` | 模型名 |
| `PROMPT_VERSION` | 提示词版本；修改提示词后必须递增 |

## 执行模式详解

### `strict`：生产推荐

- Docker 不可用：直接失败
- Docker 执行失败：只在 Docker 中重试
- 默认关闭网络
- 容器使用非 root 用户、只读根文件系统、临时目录、CPU/内存/PID 限制

### `safe-local`：本地开发

- Docker 不可用时允许本地执行生成的实验包
- 仅适合自己生成、自己审阅的实验工作区
- 不应处理陌生用户提交的代码

### `unsafe-local`：调试专用

允许本地执行工作区内代码，不提供沙箱边界。除非在隔离开发环境中，否则不要使用。

## API 主要端点

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/health` | 服务和数据库健康检查 |
| `GET` | `/metrics` | 请求数、失败数和活动任务数 |
| `POST` | `/projects` | 创建项目 |
| `POST` | `/projects/{id}/literature` | 检索文献并抽取 chunks |
| `POST` | `/projects/{id}/graph` | 构建项目图谱 |
| `GET` | `/projects/{id}/graph` | 导出项目子图 |
| `POST` | `/projects/{id}/hypotheses` | 生成假设 |
| `POST` | `/hypotheses/{id}/experiments` | 生成实验包 |
| `POST` | `/experiments/{id}/run` | 执行实验 |
| `GET` | `/experiments/{id}` | 查看实验和 runs |
| `POST` | `/projects/{id}/report` | 生成研究报告 |
| `GET` | `/reports/{id}` | 获取报告 |

### 长任务异步执行

文献、图谱、假设、实验执行和报告接口都支持 `background=true`。异步请求返回 `202` 和任务 ID，原有不带该参数的同步调用保持兼容：

```bash
curl -X POST \
  'http://127.0.0.1:8000/projects/1/literature?background=true' \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: literature-project-1-v1' \
  -d '{"query":"retrieval augmented generation","max_results":10}'

curl http://127.0.0.1:8000/jobs/1
curl 'http://127.0.0.1:8000/jobs?project_id=1&status=running'
curl -X POST http://127.0.0.1:8000/jobs/1/cancel
curl -X POST http://127.0.0.1:8000/jobs/1/retry
```

任务状态包括 `queued`、`running`、`succeeded`、`failed` 和 `cancelled`。重复提交同一个 `Idempotency-Key` 会复用原任务，不会重复消耗检索或模型资源。M2 的进程内任务执行器在 M3 增加了 worker 标识、尝试次数、心跳和重启恢复：服务重启时遗留的 `queued/running` 任务会被明确标记为 `failed/interrupted`，不会永久停留在运行中。

M4 增加自动重试和指数退避；任务执行前使用数据库条件更新抢占，多个 API worker 同时提交同一任务时只允许一个 worker 真正执行。`failed` 或 `cancelled` 任务可以通过 `POST /jobs/{id}/retry` 手动重新入队。监控系统可抓取 `GET /metrics/prometheus`，获取 Prometheus 文本格式的请求数、失败数和活动任务数。

### API 安全与请求追踪

本地开发时 `AUTORESEARCH_API_KEY` 为空，保持免鉴权。部署到共享或公网环境时应设置随机 API Key；`/health` 仍可用于探活，业务路由和 `/metrics` 需要携带以下任一请求头：

```bash
curl -H 'X-API-Key: change-me' http://127.0.0.1:8000/projects
# 或
curl -H 'Authorization: Bearer change-me' http://127.0.0.1:8000/projects
```

每个响应都会返回 `X-Request-ID` 和 `X-Process-Time-ms`。客户端可以传入自己的 `X-Request-ID`，便于把 API 日志与前端或网关日志关联。

完整可交互文档启动后访问 `/docs`。

## 测试与质量检查

```bash
pytest
ruff check .
ruff format --check .
```

真实 HTTP 和 UI 冒烟测试：

```bash
python tools/smoke.py
python tools/smoke_ui.py
```

CI 会在 Python 3.11、3.12、3.13 上运行测试，并执行 Ruff、`pip-audit` 和 Docker build。精确依赖版本记录在 [requirements.lock](requirements.lock)。

## 目录结构

```text
src/autoresearch/       核心包
  api/                  FastAPI 应用和路由
  literature/           文献检索、PDF 解析、分块
  graph/                图谱构建和查询
  hypotheses/           假设生成和排序
  experiments/          实验设计、代码生成、执行和分析
  sandbox/              Docker 沙箱
  llm/                  LLM 客户端和缓存
  ui/                   Streamlit 看板
migrations/             SQLite / PostgreSQL 迁移
 tests/                 单元、接口和生成实验测试
tools/                  冒烟与在线验收脚本
eval/                   评估问题和论文数据
 data/                  运行时数据，不提交到 Git
```

## 常见问题

### Docker 不可用，实验无法运行

这是 `strict` 模式的预期安全行为。生产环境请启动 Docker；仅在确认工作区可信的本地开发环境中使用：

```env
AUTORESEARCH_EXECUTION_MODE=safe-local
```

### arXiv 返回 406 或 Semantic Scholar 返回 429

arXiv 请求使用兼容其服务的传输方式；Semantic Scholar 建议配置 `AUTORESEARCH_SEMANTIC_SCHOLAR_KEY` 并降低检索频率。失败源会记录在流水线摘要中，不会自动伪造文献结果。

### 报告中的实验是代理实验吗

默认生成器使用 scikit-learn 小数据集验证实验机制。除非明确接入论文数据集和模型，否则报告中的结果只能视为**代理实验**，不能直接当作论文复现结论。

## 项目治理

- [SECURITY.md](SECURITY.md)：实验执行安全和漏洞报告
- [CONTRIBUTING.md](CONTRIBUTING.md)：开发与 Pull Request 要求
- [DECISIONS.md](DECISIONS.md)：技术决策记录
- [PROGRESS.md](PROGRESS.md)：阶段进度和已知问题

## 许可证

[MIT](LICENSE)
