-- 阶段 3：假设去重键（statement 归一化哈希），支撑幂等生成

ALTER TABLE hypotheses ADD COLUMN IF NOT EXISTS dedupe_key TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS hypotheses_dedupe_uidx ON hypotheses (dedupe_key);
