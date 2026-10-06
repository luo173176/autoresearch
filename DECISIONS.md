
## D-031 M7 数据库 API Key 注册表（2026-10-06）

M7 将多个 API Key 的生命周期从环境变量迁移到数据库：只保存 SHA-256 哈希与短 prefix，CLI 创建时随机生成 `ar_live_` 密钥并只展示一次；支持 label、单项目绑定、独立速率配置和按 prefix 撤销。旧的单一 `AUTORESEARCH_API_KEY` 保留为 bootstrap/admin 兼容入口。认证逻辑只接受活动注册表 Key 或配置 Key，不执行明文密钥落库。
