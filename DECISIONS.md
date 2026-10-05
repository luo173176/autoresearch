# AutoResearch 技术决策记录

原则：先跑通最小闭环再优化；本地优先；所有配置可换；每条决策可被后续阶段推翻但需在此登记。

---

## D-001 SQLite 零依赖回退后端
- **决策**：`AUTORESEARCH_DATABASE_URL` 为空时默认 SQLite；迁移按后端分目录（`migrations/postgres/`、`migrations/sqlite/`）保持同构。
- **原因**：2026-09-19 环境探测确认本机无 Docker（也无 Git），若强依赖 PG 则阶段 0 无法端到端验证。SQLite 保证「最小闭环可在任何机器跑通」，生产/团队模式走 Compose 的 PG16+pgvector。
- **代价**：db.py 需处理 JSONB↔TEXT、`%s`/`?` 占位符、`RETURNING id`/`lastrowid` 差异（已封装在 Database 类）。

## D-002 LLM 缓存 key 设计（约束 9 的超集）
- **决策**：key = sha256(prompt_version + model + messages + params)，JSON 文件落盘 `data/cache/llm/`。
- **原因**：约束要求 hash(prompt + prompt_version)；叠加 model/params 防止换模型/温度后读到旧答案。文件落盘而非数据库，使缓存随仓库目录可备份、可直接删除清理，且批处理重跑天然断点续跑。
- **使用规约**：修改任何提示词必须递增 `AUTORESEARCH_PROMPT_VERSION`。

## D-003 pgvector 延后到 0002 迁移
- **决策**：0001 建表不含 `embedding` 列；阶段 1/2 引入嵌入流水线时新增 0002（PG 加 `vector(1024)` + ivfflat 索引，SQLite 暂以 JSON 文本存储向量）。
- **原因**：0001 需在双后端可执行；pgvector 语法不可移植。bge-m3 维度 1024。

## D-004 hatchling + src 布局 + pip 安装
- **决策**：构建后端用 hatchling，src 布局，`pip install -e ".[dev]"`；本机未装 uv。
- **原因**：src 布局杜绝「未安装也能 import」的隐性 bug；hatchling 单 wheel 依赖小、editable 支持好。推荐技术栈中的 uv 在 README 标注为可选加速项。

## D-005 argparse 而非 click/typer
- **决策**：CLI 用标准库 argparse。
- **原因**：当前仅 4 个子命令，少一个依赖少一分 3.14 wheel 风险；子命令增多（阶段 4+）后再评估升级。

## D-006 OpenAI SDK 作为统一 LLM 接入层
- **决策**：用官方 `openai` 包 + 可配置 `base_url`，Ollama/DeepSeek/OpenAI 共用一套客户端；嵌入/重排端点独立配置（embed_base_url、rerank_base_url）。
- **原因**：三者均兼容 OpenAI 协议；自写 httpx 封装会重复处理流式/错误模型。

## D-007 实验代码输出独立工作区（约束 4 的落地方式）
- **决策**：所有生成的实验代码写入 `data/experiments/{experiment_id}/`，主包 `src/` 永不被实验代码触碰。
- **原因**：本机无 Git，「不直接修改主分支」以目录隔离实现；Git 就绪后叠加 `experiment/*` 分支隔离。

## D-008 Python 版本下限 3.11、本机 3.14 实测
- **决策**：`requires-python = ">=3.11"`，依赖下限写宽松（pip 自动解析支持 3.14 wheel 的最新版）。
- **实测**：2026-09-19 于 Python 3.14.7 安装成功，21 测试全绿。

## D-009 Dockerfile/Compose 先行提供、标记未实测
- **决策**：阶段 0 即提供 `Dockerfile` + `docker-compose.yml`（db/api/ui 三服务，pgvector/pg16 镜像，healthcheck 门控），但本机无 Docker 无法验证，登记为已知问题 K1。
- **原因**：接口先行可让阶段 1-5 直接假设容器化存在；用户装 Docker 后一键验收。

## D-010 JSON 列读取采用白名单反序列化
- **决策**：db.py 维护 `JSON_COLUMNS` 常量，仅对这些列做 sqlite TEXT→dict 反序列化。
- **原因**：对全行盲目 `json.loads` 会误伤内容以 `[`/`{` 开头的普通文本（如摘要）；白名单确定性强。

## D-011 冒烟脚本使用线程内真实 uvicorn + 标准库 urllib
- **决策**：`tools/smoke.py` 在进程内以线程启动真实 uvicorn Server，用 urllib 发 HTTP；`tools/smoke_ui.py` 子进程启动 headless Streamlit。
- **原因**：Windows cmd 环境下后台进程+环境变量传递脆弱；自包含脚本一条命令即可验收，且验证的是真实 HTTP 路径而非仅 TestClient。

## D-012 项目—论文用关联表而非在 papers 加 project_id（2026-09-19，阶段 1）
- **决策**：新增 `projects_papers` 关联表（迁移 0002），papers 保持全局共享 + dedupe_key 唯一去重。
- **原因**：同一论文常被多个项目的检索命中；全局去重避免重复存储与重复解析，关联表幂等。

## D-013 LLM 抽取可选化：启发式兜底保证离线可跑（2026-09-19，阶段 1）
- **决策**：文献分块的摘要/关键词抽取在 LLM 不可达时自动降级为启发式（句摘要 + 词频关键词）；探测结果按 base_url 模块级缓存。
- **原因**：本机未配 LLM 服务，兜底保证流水线离线可用、测试确定性；探测缓存避免逐论文重复探测（曾致单次验收 267s 中 240s 为重复探测）。
- **规约**：LLM 可用后重跑仍以 chunk 幂等规则跳过已建 chunk——需要增强时删除旧 chunks 重建。

## D-014 GROBID 延后（2026-09-19，阶段 1）
- **决策**：PDF 解析仅用 pymupdf；`settings.grobid_url` 预留但未实现。
- **原因**：全文文本抽取 pymupdf 已足够（实测 10/10 成功）；章节/参考文献结构化解析留到报告阶段确有需要时再接。

## D-015 pgvector embedding 列延后至 0003 迁移（阶段 2）
- **决策**：0002 只加 projects_papers；embedding 列与向量检索随阶段 2 图谱/检索增强一起上（0003：PG `vector(1024)` + ivfflat，SQLite 暂 JSON 文本）。

## D-016 arXiv 检索走标准库 urllib 传输（2026-09-19，阶段 1，重要环境事实）
- **决策**：arXiv 真实流量用 `urllib.request`（浏览器兼容 UA），注入 httpx client 的路径仅用于测试。
- **原因**：实测 arXiv WAF 按客户端指纹拦截——httpx 的多词/短语查询一律 406（UA 换成 Mozilla 也 406、等待冷却无效、IP 级排除），同一 URL/参数用标准库 urllib 放行（50 条正常返回）。S2/PubMed 无此问题，保持 httpx。
- **教训**：`_get_with_retry` 同时覆盖 406/429/5xx；对 API 的反爬行为要用最小探测定位，避免高频试探触发更长惩罚。

## D-017 图谱双路抽取：规则词典兜底 + LLM 主路（2026-09-19，阶段 2）
- **决策**：`graph/builder.py` 以「LLM JSON 抽取为主、内置词典规则为兜底」双路运行；规则路径含 130+ 方法/数据集/指标词典、句级极性分析（结论）、缺口句式、跨论文矛盾配对。
- **原因**：本机无 LLM 服务时图谱仍可构建（离线优先原则）；LLM 就绪后零改动提质。LLM 输出解析失败按 chunk 回退，不整体失败。

## D-018 SQLite 性能三连修：连接复用 + WAL（2026-09-19，阶段 2，重要性能事实）
- **决策**：SQLite 连接按线程复用（threading.local）+ `PRAGMA journal_mode=WAL` + `synchronous=NORMAL`。
- **实测**：图谱构建 733 chunks 从 786s → 480s（连接复用）→ **3.8s**（WAL）。根因：逐查询新建连接 + 每查询 commit 在 Windows 触发 fsync（~30ms/次 × 1 万+ 次写）。
- **规约**：db.connection() 的 commit 语义保留（无写事务时 no-op）；本地单写者场景 WAL 无并发风险；.gitignore 已覆盖 -wal/-shm 伴生文件。

## D-019 PDF 噪声句过滤（2026-09-19，阶段 2）
- **决策**：finding/gap 抽取前过 `_looks_like_sentence`（长度 40-300、≥6 词、禁含 URL/邮箱/代码/表格/项目符号特征、参考文献条目正则）。
- **原因**：pymupdf 全文里表格行、代码行、邮箱页脚、参考文献条目会伪装成句子，首跑产生 142 findings 中大量垃圾 + 661 对假矛盾；过滤后 85 findings / 182 矛盾对，Top 实体回到主题实体。
- **遗留**：极性词表启发式仍会放进个别弱句（K7），LLM 路径可解。

## D-020 假设去重用语义键而非纯文本相似（2026-09-19，阶段 3）
- **决策**：ranker 两级去重——先按 `dedupe_key_semantic`（来源+实体组合，如 `contradiction|rag|自然问答`）合并，再用文本 Jaccard 0.95 兜底；hypotheses 表另加 dedupe_key（statement sha1）唯一索引保证入库幂等。
- **原因**：模板句共享骨架词，纯 Jaccard 0.8 会把不同实体组合的假设误杀（实测 96 候选只剩 36 条 <50 验收线）；语义键去重后 114 候选 → 50 条且多样性恢复。
- **附**：同方法的多个矛盾对语义键相同属有意收敛——同一方法×同一条件的矛盾本质是同一研究问题。

## D-022 表格代理实验设计（2026-09-19，阶段 4）
- **决策**：实验代码生成器产出 scikit-learn 代理实验（iris/wine/breast_cancer × 多种子 × 多折，proposed=gradient_boosting/random_forest vs baseline=logistic_regression），设计 `note` 显式声明代理性质；假设原方向（如 reranking 级联）记录在设计中。
- **原因**：本机无 GPU/LLM，检索类方法无法直接执行；代理闭环验证「设计→代码→执行→统计检验→报告」机制本身。接入真实数据集/模型后仅需替换 config.json 的 estimator 规格，流程不变。fetch_openml 已内建支持（source=openml）。

## D-023 执行器 docker→local 逐级降级（2026-09-19，阶段 5，实测环境）
- **决策**：`run_experiment` 生成执行计划 [docker, local, ...]：Docker 可用先走沙箱（--cpus/--memory 限制），镜像拉取/守护进程失败自动回退本地子进程；`sandbox_enabled=false` 可强制本地。
- **原因**：实测本机 Docker Desktop 可用但 Docker Hub 网络阻断——单一判断 `is_docker_available()` 不足以保证沙箱可用；降级计划让闭环在任何环境可跑，run 元数据记录真实 executor。约束 3 的完整满足以镜像加速器配置为前提（K10）。

## D-024 code_path 归属 runs 表（2026-09-19，阶段 4）
- **决策**：实验工作区路径确定性为 `data/experiments/{experiment_id}/`，code_path 字段记录在 runs 行（与规范数据模型一致），experiments 表不加列。
- **原因**：规范数据模型即如此定义；确定性路径使 run_experiment 无需读实验行即可定位代码。

## D-025 统计检验用精确符号检验（2026-09-19，阶段 4/5）
- **决策**：proposed vs baseline 逐折配对差的精确符号检验（p = 2·P(Bin(n,0.5) ≤ min(w,l))，math.comb 计算）。
- **原因**：零依赖（scipy 未在依赖中）、精确无近似、对折数少（5×3 seeds=15 对）稳健；生成代码自包含，沙箱内无需额外装包。分析器同时给出方差诊断与迭代建议。

## D-021 假设生成的项目前置校验（2026-09-19，阶段 3）
- **决策**：`generate_hypotheses` 要求项目已有 chunks（projects_papers 关联），否则 409。
- **原因**：图谱是全局共享的，若无项目级校验，空项目也能"借"全局图谱生成假设，语义上不合理。

## D-026 进程内后台任务与异步 API（2026-10-04，阶段 8）

M2 为文献、图谱、假设、实验执行和报告生成增加可选的 `background=true` 模式。任务状态持久化在 `jobs` 表，使用进程内 `ThreadPoolExecutor` 执行；不带该参数的同步调用保持兼容。`Idempotency-Key` 由数据库唯一约束保证重复请求复用既有任务，不重复消耗检索或模型资源。当前实现不引入 Redis/Celery；未来可以替换任务提交器而不改变 API 契约。
