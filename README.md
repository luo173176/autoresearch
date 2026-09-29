# AutoResearch 🔬

自主科研与实验平台：输入研究问题、领域和计算预算，自动完成 **文献调研 → 知识图谱 → 假设生成 → 实验设计 → 代码生成 → 沙箱运行 → 结果分析 → 论文初稿**，输出可复现实验包。

> 当前状态：**阶段 0-7 全部完成**——端到端闭环已实测打通（真实语料：50 篇 arXiv RAG 论文 → 209 实体图谱 → 50 条假设 → 实验执行与统计检验 → 带引用报告）。详见 [PROGRESS.md](PROGRESS.md) 与 [DECISIONS.md](DECISIONS.md)。

## 架构总览

```
研究问题 ──▶ 文献检索(arXiv/S2/PubMed/本地PDF) ──▶ 知识图谱(方法/数据集/指标/矛盾/缺口)
                                                        │
可复现实验包 ◀── 报告生成 ◀── 结果分析 ◀── Docker沙箱 ◀── 代码生成 ◀── 假设生成 ◀─┘
                                          (资源限制/重试)           (可验证/有基线)
```

- **后端**：FastAPI + Uvicorn（API）
- **看板**：Streamlit（项目/图谱/实验/报告）
- **数据库**：PostgreSQL 16 + pgvector（生产）/ SQLite（零依赖本地模式，默认）
- **LLM**：OpenAI-compatible API，可配置 base_url/api_key/model（Ollama / DeepSeek / OpenAI）
- **沙箱**：Docker SDK for Python（阶段 5）

## 最简使用（零命令行，10 秒上手）

**方式一（推荐）**：双击桌面快捷方式 **`AutoResearch`**（已创建），或双击项目目录下的 **[`一键启动.bat`](一键启动.bat)** → 浏览器自动打开看板 → 默认页就是「🚀 一键研究」→ 输入研究问题 → 点「开始自动研究」→ 约 1-3 分钟后报告直接显示在页面上。

- 无需任何 API Key：LLM 可用时自动增强，不可用时走内置词典规则，全流程照常完成
- 关闭命令行窗口即退出服务

**配置大模型 API（可选，推荐）**：看板左侧切到 **「⚙️ 设置」** → 选预设（DeepSeek/OpenAI/智谱/Ollama）或手填 → 粘贴 API Key → 点 **「🔍 测试连接」**（真实发一条消息验证）→ 点 **「💾 保存配置」**。配置写入项目根 `.env`，立即生效无需重启；随后「🚀 一键研究」的图谱与假设自动切换为 LLM 增强。

**方式二（命令行一条命令）**：

```bash
.venv\Scripts\autoresearch auto "你的研究问题"          # 文献→图谱→假设→实验→报告 一条龙
.venv\Scripts\autoresearch config --test               # 命令行查看/验证 LLM 配置
```

## 30 分钟快速开始

### 前置要求

- Python ≥ 3.11（已在 Python 3.14 上实测）
- 可选：Docker（用于 PostgreSQL + pgvector 生产模式与阶段 5 沙箱；未安装时默认使用 SQLite）

### 1. 安装

```bash
cd autoresearch
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"     # Windows
# Linux/macOS: .venv/bin/python -m pip install -e ".[dev]"
```

### 2. 配置（可选）

```bash
copy .env.example .env    # 默认 SQLite + Ollama，本地零依赖即可跑通
```

关键配置见下方 [环境变量](#环境变量)。无 LLM Key 也能完成阶段 0 全部功能（LLM 调用发生在后续阶段）。

### 3. 初始化并启动

```bash
.venv\Scripts\autoresearch init      # 建数据目录 + 跑数据库迁移
.venv\Scripts\autoresearch serve     # API: http://127.0.0.1:8000  (GET /health)
.venv\Scripts\autoresearch ui        # 看板: http://localhost:8501
```

### 4. 验证

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok","app":"AutoResearch","version":"0.1.0","backend":"sqlite","database":true,...}
```

### 5. 测试与冒烟

```bash
.venv\Scripts\python -m pytest          # 单元/接口测试
.venv\Scripts\python tools\smoke.py     # 端到端：真实 uvicorn + /health + 创建项目
.venv\Scripts\python tools\smoke_ui.py  # Streamlit 启动冒烟
```

### Docker Compose 方式（PostgreSQL 16 + pgvector）

```bash
docker compose up -d --build
# API http://localhost:8000  |  UI http://localhost:8501  |  PG localhost:5432
```

> 注：Compose 路径需要本机安装 Docker；Dockerfile/compose 尚未在无 Docker 环境下实测（见 PROGRESS.md 已知问题）。

## 环境变量

所有变量前缀 `AUTORESEARCH_`，完整清单见 [.env.example](.env.example)。核心项：

| 变量 | 说明 | 默认 |
|---|---|---|
| `DATABASE_URL` | PostgreSQL DSN；留空用 SQLite | 空 |
| `SQLITE_PATH` | SQLite 文件路径 | `data/autoresearch.db` |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | OpenAI-compatible LLM | Ollama 本地 |
| `EMBED_BASE_URL` / `EMBED_MODEL` | 嵌入模型（bge-m3） | Ollama 本地 |
| `RERANK_BASE_URL` / `RERANK_MODEL` | 重排模型（bge-reranker-v2-m3） | Ollama 本地 |
| `PROMPT_VERSION` | 提示词版本，参与 LLM 缓存 key | `v0` |
| `DATA_DIR` | 数据根目录 | `data` |

## CLI

| 命令 | 说明 | 状态 |
|---|---|---|
| `autoresearch auto "问题"` | **一键全流程**：文献→图谱→假设→实验→报告 | ✅ 推荐入口 |
| `autoresearch init` | 初始化数据目录与数据库迁移 | ✅ 阶段 0 |
| `autoresearch serve` | 启动 FastAPI | ✅ 阶段 0 |
| `autoresearch ui` | 启动 Streamlit 看板 | ✅ 阶段 0 |
| `autoresearch literature "问题"` | 三源检索+去重入库+分块抽取（`--sources arxiv,s2,pubmed --download-pdfs --no-llm`） | ✅ 阶段 1 |
| `autoresearch graph` | 构建知识图谱（`--project --no-llm --export graph.json`） | ✅ 阶段 2 |
| `autoresearch hypotheses` | 生成研究假设（矛盾/缺口/组合三来源，`--max --no-llm`） | ✅ 阶段 3 |
| `autoresearch experiment` | 由假设生成实验代码包（`--hypothesis --run`） | ✅ 阶段 4 |
| `autoresearch run <id>` | 执行实验（docker→local 降级 + 重试） | ✅ 阶段 5 |
| `autoresearch report` | 生成带引用研究报告（`--export`） | ✅ 阶段 6 |
| `autoresearch watch` | 定时扫描新论文→刷新图谱/假设（`--interval --once`） | ✅ 阶段 7 |
| `autoresearch eval` | 端到端评估（需外网） | ✅ 阶段 6 |

> 文献阶段提示：Semantic Scholar 未认证限流严格（429），建议配置 `AUTORESEARCH_SEMANTIC_SCHOLAR_KEY`；arXiv 检索内部使用 urllib 传输以绕过其 WAF 对 httpx 指纹的拦截（见 DECISIONS.md D-016）；LLM 不可达时抽取自动降级启发式，离线可跑。

## API

| 端点 | 说明 | 状态 |
|---|---|---|
| `GET /health` | 健康检查（后端/数据库状态） | ✅ |
| `POST /projects` | 创建项目（问题/领域/预算） | ✅ |
| `GET /projects`、`GET /projects/{id}` | 项目列表/详情 | ✅ |
| `POST /projects/{id}/literature` | 文献检索+分块抽取（同步执行） | ✅ 阶段 1 |
| `GET /projects/{id}/papers` | 项目论文列表 | ✅ 阶段 1 |
| `POST /projects/{id}/graph` | 构建知识图谱（幂等） | ✅ 阶段 2 |
| `GET /projects/{id}/graph` | 导出项目子图 {nodes, links} | ✅ 阶段 2 |
| `POST /projects/{id}/hypotheses` | 生成假设（幂等） | ✅ 阶段 3 |
| `GET /projects/{id}/hypotheses` | 假设列表 | ✅ 阶段 3 |
| `POST /hypotheses/{id}/experiments` | 生成实验代码包 | ✅ 阶段 4 |
| `POST /experiments/{id}/run`、`GET /experiments/{id}` | 执行/查询实验 | ✅ 阶段 5 |
| `POST /projects/{id}/report`、`GET /reports/{id}` | 报告生成/获取 | ✅ 阶段 6 |

交互式文档：启动后访问 <http://127.0.0.1:8000/docs>。

## 一条命令跑通全流程

```bash
.venv\Scripts\autoresearch literature "retrieval augmented generation" --max 50 --sources arxiv
.venv\Scripts\autoresearch graph
.venv\Scripts\autoresearch hypotheses
.venv\Scripts\autoresearch experiment --run      # 生成实验并执行（docker→local 自动降级）
.venv\Scripts\autoresearch report --project 1 --export data\artifacts\report.md
```

## LLM 缓存与断点续跑

- 缓存 key = `sha256(prompt_version + model + messages + params)`，落盘 `data/cache/llm/<前2位>/<hash>.json`
- 批处理任务中断后重跑：已完成的 prompt 命中缓存，不再消耗 token
- 修改提示词后必须递增 `AUTORESEARCH_PROMPT_VERSION`，否则读到旧缓存

## 目录结构

```
autoresearch/
├── src/autoresearch/       # 主包（config/db/models/schemas/llm/api/ui/literature/graph/...）
├── migrations/             # postgres/ 与 sqlite/ 两套迁移
├── data/                   # papers/ cache/ artifacts/ experiments/（运行时生成）
├── eval/                   # 评估用例（questions.jsonl / papers.json）
├── tests/                  # pytest
├── tools/                  # 冒烟脚本 smoke.py / smoke_ui.py
├── docker-compose.yml      # PG16+pgvector / API / UI 一键启动
└── .env.example
```

## 常见问题

- **端口占用**：改 `.env` 中 `AUTORESEARCH_API_PORT` / `AUTORESEARCH_UI_PORT`
- **Ollama 未启动**：阶段 0 不调用 LLM，不影响；后续阶段调用失败时启动 `ollama serve` 或改 `.env` 指向 DeepSeek/OpenAI
- **Python 3.14**：依赖均需含 3.14 wheel 的版本（pip 会自动解析最新版），已在 3.14.7 实测
