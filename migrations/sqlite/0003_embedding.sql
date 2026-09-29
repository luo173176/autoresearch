-- 阶段 2：SQLite 侧 embedding 列（JSON 数组文本存储；与 PG pgvector 版同构预留）

ALTER TABLE chunks ADD COLUMN embedding TEXT;
