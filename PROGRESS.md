

## 阶段 11 交付明细（2026-10-05）

M5 已新增独立 `autoresearch worker` 进程：共享数据库队列、轮询 queued 任务、受控 handler 工厂、跨进程原子抢占和 `--once` 一次性 drain 模式。API 内置执行器作为本地开发兼容模式保留；生产环境可将 API 与多个 worker 分开部署。
