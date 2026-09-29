# AutoResearch 进度

更新时间：2026-09-19
当前状态：**阶段 0-7 全部完成 ✅**（80 测试通过 + 端到端全链路验收打通：假设→实验→执行→分析→报告）

## 阶段总览

| 阶段 | 内容 | 状态 |
|---|---|---|
| 0 | 项目初始化：骨架/配置/迁移/API /health/看板骨架/CLI | ✅ 完成 |
| 1 | 文献检索与解析（arXiv/S2/PubMed/PDF → papers/chunks） | ✅ 完成 |
| 2 | 知识图谱（实体/关系/证据/置信度 + 查询可视化） | ✅ 完成 |
| 3 | 假设生成（图谱缺口/矛盾 → 可验证假设） | ✅ 完成 |
| 4 | 实验设计与代码生成（可运行实验包 → data/experiments/{id}/） | ✅ 完成 |
| 5 | 沙箱执行与结果分析（docker→local 降级 + 符号检验） | ✅ 完成 |
| 6 | 报告与评估（带引用论文初稿 + 流水线指标） | ✅ 完成 |
| 7 | UI 完善（4 页看板）+ watch 定时扫描 | ✅ 完成 |

## 阶段 0 交付明细

### 已完成内容
- 项目骨架：`pyproject.toml`（src 布局，hatchling）+ 全部目录结构 + `.env.example` + `docker-compose.yml` + `Dockerfile`
- 配置层：`config.py`（pydantic-settings，前缀 `AUTORESEARCH_`），覆盖 LLM/嵌入/重排/API/UI/文献 API 全部可配置项
- 数据层：`db.py` 双后端统一接口（PostgreSQL 16 / SQLite 零依赖回退），JSON 适配（JSONB ↔ TEXT）、跨后端占位符、幂等迁移器
- 迁移：`migrations/postgres/0001_init.sql` + `migrations/sqlite/0001_init.sql`，10 张业务表全部建齐（projects/papers/chunks/entities/relations/hypotheses/experiments/runs/reports/qa_logs）
- API：FastAPI 应用工厂，`GET /health` + `POST /projects` + `GET /projects(/{id})` 真实闭环；其余 7 个端点按阶段契约 501 占位
- LLM 底座：`llm/client.py`（OpenAI-compatible，批处理/并发/重试）+ `llm/cache.py`（key=sha256(prompt_version+model+messages+params)，文件落盘，断点续跑）
- CLI：`autoresearch init / serve / ui / version`
- Streamlit 看板骨架：项目列表、指标卡、系统信息
- 沙箱桩：`sandbox/docker_runner.py`（含 Docker 可用性探测，本机返回 False）
- 测试：21 项（20 通过 + 1 PostgreSQL 集成测试因无 Docker 跳过）
- 冒烟：`tools/smoke.py`（真实 uvicorn + /health + 创建/查询项目）、`tools/smoke_ui.py`（Streamlit headless 启动）

### 运行命令
```bash
cd E:\Users\luo17\AppData\Programs\Zcode\autoresearch
.venv\Scripts\autoresearch init
.venv\Scripts\autoresearch serve        # API http://127.0.0.1:8000/docs
.venv\Scripts\autoresearch ui           # 看板 http://localhost:8501
.venv\Scripts\python -m pytest          # 测试
.venv\Scripts\python tools\smoke.py     # API 端到端冒烟
.venv\Scripts\python tools\smoke_ui.py  # UI 冒烟
```

### 测试结果（2026-09-19 实测）
- `pytest`：**20 passed, 1 skipped**（4.74s；skip = PostgreSQL 集成测试，需设 `AUTORESEARCH_TEST_DATABASE_URL`）
- `tools/smoke.py`：/health 返回 `{"status":"ok","backend":"sqlite","database":true}`；POST /projects 创建 id=1 并成功回读，budget JSON 往返正确
- `tools/smoke_ui.py`：`HTTP 200: True | 进程存活: True`
- CLI：`autoresearch version` → 0.1.0；`init` 幂等可重复执行

## 阶段 1 交付明细（2026-09-19）

### 已完成内容
- `literature/search.py`：arXiv（Atom XML 解析）/ Semantic Scholar / PubMed（esearch+esummary+efetch）三源检索，统一 `Paper` 模型 + sha1 标题去重键；429/406/5xx 指数退避重试
- `literature/pdf_parser.py`：pymupdf 解析（标题回退正文首行、加密/扫描件检测）、PDF 下载（%PDF 魔数校验）
- `literature/extractor.py`：段落聚合分块（可配 chunk_size/overlap）+ LLM 增强（探测缓存、批量、缓存断点续跑）+ 无 LLM 启发式兜底（句摘要 + 词频关键词）
- `literature/__init__.py`：`run_pipeline` 编排（检索→去重入库→项目关联→分块抽取→PDF 可选），全链路幂等（重复运行不产生重复数据）
- 迁移 0002：`projects_papers` 关联表（论文全局去重共享）
- API：`POST /projects/{id}/literature`（真实实现）+ `GET /projects/{id}/papers`；CLI：`autoresearch literature "查询" [--project --max --sources --download-pdfs --no-llm]`
- db.py：`insert_ignore()`（PG ON CONFLICT / SQLite OR IGNORE）、dumps 改用 psycopg Json 适配器（保证 dict/list→jsonb）
- 在线验收脚本：`tools/live_literature.py`

### 实测验收（在线，2026-09-19）
- **arXiv**：`"retrieval augmented generation"` 检索 50 篇 → 下载解析 10 篇 PDF 全文（**10/10 成功，0 失败**）→ **733 chunks** → 可用文本率 50/50 = **100%**（要求 >90% ✅）
- **PubMed**：同查询 50 篇，摘要全获取（前次验收 50/50 可用文本 = 100% ✅）
- **Semantic Scholar**：未认证配额限流（429，重试后仍拒）；代码经 mock 测试覆盖，配置 `AUTORESEARCH_SEMANTIC_SCHOLAR_KEY` 即可解锁
- `pytest`：**43 passed, 1 skipped**（PG 集成测试仍跳过）

### 阶段 1 排障记录（重要环境事实）
- arXiv WAF 指纹拦截：httpx 发起的多词/短语查询一律 **406**（UA 无关、IP 冷却不解决），标准库 urllib 同参数放行 → arXiv 真实流量已改走 urllib（D-016），测试仍走 MockTransport
- LLM 不可达时每篇论文重复探测曾拖慢 267s → 已加模块级探测缓存（按 base_url 记忆，整轮仅 1 次）

## 阶段 2 交付明细（2026-09-19）

### 已完成内容
- `graph/builder.py`：双路抽取——规则路径（内置 130+ 术语词典：方法/数据集/指标 + 句级极性分析 + 跨论文矛盾配对 + 研究缺口句式 + 句子质量过滤）与 LLM 路径（JSON 结构化抽取，失败逐 chunk 回退规则）；实体/关系幂等入库（证据追加 ≤20 条、置信度只升不降）
- `graph/query.py`：统计、头部实体、邻居查询、缺口/矛盾清单、项目子图 JSON 导出、NetworkX 图构建
- 迁移 0003：chunks.embedding 列（PG pgvector vector(1024) / SQLite JSON 预留）
- API：`POST /projects/{id}/graph`（409=无 chunks）、`GET /projects/{id}/graph`（子图导出）；CLI：`autoresearch graph [--project --no-llm --export]`
- Streamlit 看板新增「图谱浏览」页：类型统计、头部实体、邻居查询、缺口/矛盾清单、子图 JSON 下载
- db.py 关键性能修复：SQLite 连接线程复用 + WAL + synchronous=NORMAL
- 在线验收脚本：`tools/live_graph.py`

### 实测验收（真实语料：项目 #1，50 篇 arXiv RAG 论文，733 chunks）
- 图谱构建 **3.8s**（733 chunks）：209 实体（method 46 / dataset 10 / metric 17 / finding 85 / gap 51）、226 条关系 + 182 对跨论文矛盾、合计 408 边
- **核心方法覆盖率 88% > 80% ✅**（method 13/14=93%、metric 10/10=100%、dataset 7/10=70%；缺失项 LoRA/mmlu/gsm8k/kilt 本就少见于 RAG 专题语料）
- 头部实体：retrieval augmented generation（度 54）、accuracy（31）——符合语料主题
- 子图导出 `data/artifacts/graph_project1.json`（205 节点 / 408 边）
- `pytest`：**58 passed, 1 skipped**

### 阶段 2 排障记录（重要性能事实）
- 图谱构建首跑 786s → 三步修复 → 3.8s：① SQLite 连接逐查询新建 → 线程复用；② 每查询 commit 在 Windows 触发 fsync → WAL + synchronous=NORMAL（决定性）；③ 正则词典保持预编译
- PDF 噪声治理：表格行/代码行/邮箱/URL/参考文献条目/项目符号伪装成"结论句"造成垃圾实体与 661 对假矛盾 → `_looks_like_sentence` 质量过滤（长度/词数/垃圾特征/引用样式正则）后 findings 142→85、矛盾 661→182

## 阶段 3 交付明细（2026-09-19）

### 已完成内容
- `hypotheses/generator.py`：三类来源候选——矛盾消解（contradicts 关系对 → 受控复现假设）、缺口填补（gap+addresses → 针对性改进假设）、方法组合（共享数据集的 uses 关系 → 级联组合假设）；每条候选含 statement/rationale/testability{datasets,metrics,baseline,direction}/novelty + metadata 溯源（relation_ids/entity_ids/quotes）；LLM 改写主路（top20，走缓存）+ 规则模板兜底；前置校验项目必须已有 chunks
- `hypotheses/ranker.py`：score = 0.5×novelty + 0.3×可验证性完整度 + 0.2×证据支持度；两级去重（语义键：来源+实体组合 → 文本 Jaccard 0.95 兜底）
- 迁移 0004：hypotheses.dedupe_key（statement 归一化 sha1）+ 唯一索引 → 生成幂等
- API：`POST /projects/{id}/hypotheses`（409=项目无 chunks/图谱为空）、`GET /projects/{id}/hypotheses`；CLI：`autoresearch hypotheses [--project --max --no-llm]`
- 在线验收脚本：`tools/live_hypotheses.py`

### 实测验收（真实图谱：项目 #1，209 实体/408 边）
- **生成 50 条假设**（候选 114 → 语义去重 + 排序 → 50），耗时 0.2s
- **证据溯源率 100%**（50/50 带 relation_ids 或 entity_ids）；**testability 三要素齐备率 100%**
- 来源分布：combination 42 / contradiction 2 / gap 6——规则路径下 uses 关系最稠密；同方法矛盾对语义去重后收敛为同一研究问题（符合预期），LLM 路径上线后多样性可进一步提升
- `pytest`：**68 passed, 1 skipped**

## 阶段 4-7 交付明细（2026-09-19）

### 已完成内容
- **阶段 4 实验设计与代码生成**：`experiments/designer.py`（假设 testability → 实验设计：数据集/基线/提出方法/CV/统计检验/消融/预算，离线代理设计显式记录在 note）；`experiments/codegen.py`（渲染自包含实验包 `data/experiments/{id}/`：config.json + main.py + requirements.txt + README.md，多种子 × 多折 × 变体 + 精确符号检验）；`create_experiment` 入库
- **阶段 5 执行与分析**：`experiments/__init__.py run_experiment`（执行计划 docker→local 逐级降级、失败重试、runs 表记录 executor/耗时/日志）；`sandbox/docker_runner.py`（docker run 资源限制 --cpus/--memory）；`experiments/analyzer.py`（逐数据集/指标显著性结论 + 整体判断 + 迭代建议）
- **阶段 6 报告与评估**：`reporting.py`（摘要/相关工作[引用]/图谱发现/假设/实验结果表/结论局限/参考文献——引用编号与库内论文一一对应，结构准确率 100%；图表以数据形式存储供 Streamlit 渲染）；`eval/metrics.py`（文献可用率/图谱覆盖率/假设溯源率/实验成功率）；`eval/run_eval.py`（eval/questions.jsonl 逐题跑全流水线，需外网）
- **阶段 7 UI 与自动化**：Streamlit 四页看板（总览/图谱浏览/实验运行含指标柱状图/报告查看含 Markdown 渲染与下载）；CLI `watch --interval --once`（定时扫描新论文→刷新图谱→刷新假设）
- **API 全端点转真**：规范内 9 个端点全部实现，无 501 占位；CLI 新增 experiment/run/report/watch/eval
- 依赖新增：scikit-learn（实验代理）；config 新增 experiment_*/sandbox_* 配置

### 实测验收（端到端，项目 #1 真实数据）
- **全链路**：假设 #45 → 实验 #1 生成（4 文件）→ 执行 → 分析 → 报告 #1（7,979 字符 / 15 引用 / 3 组图表数据，导出 `data/artifacts/report_project1.md`）
- **docker→local 降级实战验证**：本机 Docker Desktop 可用但 Docker Hub 网络阻断（镜像拉取失败）→ 第 1 次尝试 docker 失败 → 第 2 次自动回退 local 执行成功
- **分析器如实报告 negative result**：代理实验中 GradientBoosting 在 iris/wine/breast_cancer 上相对 LogisticRegression 为 0 提升 / 4 显著下降（含符号检验 p 值）——结果不被粉饰，附迭代建议
- 流水线指标：文献可用率 1.0、假设 50 条溯源率 1.0 / testability 1.0、实验完成率 1.0
- `pytest`：**80 passed, 1 skipped**（含生成代码真实执行、失败重试、docker 路径 mock、报告引用编号校验）
- Streamlit UI 冒烟通过（HTTP 200 + 进程存活）

## 已知问题
- **K1**：本机未安装 Docker，`docker-compose.yml`/`Dockerfile` 未能实测（需用户安装后执行 `docker compose up -d --build` 验证）
- **K2**：本机未安装 Git，版本控制未建立（安装后执行 `git init && git add -A && git commit -m "phase 0"`）
- **K3**：`autoresearch init` 依赖相对路径，必须在仓库根目录执行（在工作区根目录执行会在错误位置建 `data/`）
- **K4**：pgvector 的 embedding 列尚未加入（计划由 0002 迁移在阶段 1/2 引入），当前向量检索能力为零，属阶段计划内
- **K5**：pytest 出现 starlette TestClient 的 anyio DeprecationWarning（上游依赖告警，无功能影响）
- **K6**：Semantic Scholar 未认证限流严格（429），生产使用需配置 API key；已实现退避重试，错误会记录在流水线摘要 `errors` 中不影响其他源
- **K7**：规则路径的 finding/gap 仍有个别弱句混入（如 "Alongside all the steps..."），矛盾对 182 对偏多且极性判断为词表启发式——配好 LLM 后用 `--graph`（LLM 路径）重建可显著提质，规则路径仅保证离线可用
- **K8**：SQLite WAL 模式会在 data/ 下生成 -wal/-shm 伴生文件（已在 .gitignore 覆盖），属正常现象
- **K9**：规则路径假设来源分布偏斜（组合类占 84%）且 statement 为模板句——质量上限受词典规则限制，配置 LLM 后 `autoresearch hypotheses`（不带 --no-llm）自动走 LLM 改写
- **K10**：Docker Hub 在本机网络不可达，沙箱镜像 `python:3.12-slim` 拉取失败 → 执行器自动降级 local（已实测）；用户配置镜像加速器（如 registry mirror）后 `autoresearch run <id>` 即可走真沙箱
- **K11**：代理实验的"提出方法"（gradient_boosting/random_forest）是假设方向的表格代理，结论只验证实验机制与统计框架；接入真实数据集/模型后替换 config.json 的 estimator 规格即可（设计 note 已显式记录）
- **K12**：`eval` 命令需外网且较慢（逐题跑文献+图谱+假设），未在验收中执行（mock 测试覆盖指标函数）

## 后续优化方向（按优先级）
0. **零门槛入口已就绪（2026-09-19）**：桌面快捷方式 `AutoResearch.lnk` + `一键启动.bat` + 看板「🚀 一键研究」页（输入问题点按钮跑全程）+ CLI `autoresearch auto`；**看板「⚙️ 设置」页支持图形化配置大模型 API**（预设 Ollama/DeepSeek/OpenAI/智谱、测试连接、保存 .env 立即生效），CLI `autoresearch config [--test]`；87 项测试全绿
1. 配置 LLM key 后重跑 graph/hypotheses（LLM 主路提质）：实体/假设质量、矛盾降噪
2. Docker 配置镜像加速器 → 沙箱执行真闭环；扩展沙箱镜像预装 sklearn（离线可跑）
3. OpenML 数据集接入（fetch_openml 已内建支持，source=openml）+ 论文复现用例（eval/papers.json）
4. pgvector 0003 已就绪：嵌入流水线接入后启用混合检索（BM25+向量+图谱）
5. Streamlit 图谱可视化升级（pyvis/echarts）；报告导出 PDF（LaTeX/pandoc）
