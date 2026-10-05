
## D-027 M3 鉴权、任务恢复与请求可观测性（2026-10-05）

M3 不引入 Redis/Celery，而是在现有进程内执行器上补齐可诊断边界：任务记录 worker_id、attempt_count、heartbeat_at；应用启动时将上次进程遗留的 queued/running 任务标记为 failed/interrupted，避免客户端无限等待。API Key 采用可选配置，空值保持本地兼容，非空时保护业务路由和 metrics，health 保留探活能力。所有响应增加 X-Request-ID 与 X-Process-Time-ms，并提供轻量 JSON metrics；后续如扩展多进程队列，可沿用 jobs 表和 API 契约。
