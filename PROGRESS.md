

## 阶段 8-9 交付明细（2026-10-05）

M2 已完成后台任务闭环：jobs 双后端迁移、background=true 异步端点、任务查询/取消、幂等键和进程内 worker。M3 在此基础上增加可选 API Key 鉴权、Request-ID/耗时响应头、JSON metrics、worker 心跳、尝试次数以及服务重启后的中断任务恢复。新增测试覆盖鉴权、请求追踪、指标和恢复逻辑。
