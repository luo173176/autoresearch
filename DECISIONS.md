
## D-030 M6 项目范围权限、限流与优先级（2026-10-06）

M6 采用单 API Key 可选项目绑定：`API_KEY_PROJECT_ID` 限制该 key 对项目及关联假设、实验、任务资源的访问，保持现有全局 key 和本地空 key 兼容。限流先采用进程内滑动窗口，避免新增 Redis 依赖；多实例部署由网关/Redis 负责全局限流。任务 priority 持久化在 jobs 表，worker 按 priority DESC、id ASC 调度，客户端通过 `X-Job-Priority` 提交且由服务端做上下界限制。
