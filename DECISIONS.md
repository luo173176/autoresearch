
## D-028 M4 自动重试与数据库抢占（2026-10-05）

M4 在不引入 Redis/Celery 的前提下，将任务执行增强为可重试且跨进程提交安全：每次尝试先通过 `UPDATE ... WHERE status='queued'` 原子抢占，只有更新成功的 worker 执行 handler；临时失败按配置次数和指数退避重新入队，最终失败才进入 failed。手动重试根据 jobs.input 重建 handler，而不是把 Python 闭包序列化进数据库。另提供 Prometheus 文本格式指标出口，便于后续接入监控系统。
