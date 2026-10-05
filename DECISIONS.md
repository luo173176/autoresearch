
## D-029 M5 独立数据库队列 worker（2026-10-05）

M5 提供 `autoresearch worker` 独立进程，轮询持久化 jobs 队列并根据受控任务类型重建 handler。API 内置执行器继续保留作为本地开发模式；生产部署可以运行多个 worker。执行前的数据库条件更新负责跨进程原子抢占，避免同一任务重复执行。handler 只允许已注册的 literature/graph/hypotheses/experiment_run/report 类型，不从数据库执行任意代码。
