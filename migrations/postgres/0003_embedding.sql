-- 阶段 2：为 chunks 预置 embedding 列（pgvector；维度 1024 = bge-m3）
-- 嵌入流水线在检索增强阶段填充；本迁移仅就绪 schema（DECISIONS.md D-015）

CREATE EXTENSION IF NOT EXISTS vector;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS embedding vector(1024);
