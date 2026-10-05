"""数据库访问层：PostgreSQL（生产）+ SQLite（零依赖本地模式）统一最小接口。

- 迁移 SQL 按后端分目录：migrations/postgres/、migrations/sqlite/
- JSON 字段：PostgreSQL 用 JSONB（psycopg 自动把 dict 适配为 jsonb）；
  SQLite 存 TEXT，由本层按 JSON_COLUMNS 白名单在读取时反序列化
- 占位符差异：psycopg 用 %s，sqlite3 用 ?，统一通过 db.ph 引用
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

from loguru import logger

from .config import Settings, get_settings

try:  # SQLite 模式下 psycopg 非必需
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None  # type: ignore[assignment]

POSTGRES_SCHEMES = ("postgres://", "postgresql://", "postgresql+")

# 这些列在 SQLite 中存 JSON 字符串，读取时反序列化；PostgreSQL 为 JSONB 直接得到 dict
JSON_COLUMNS = frozenset(
    {
        "budget",
        "authors",
        "metadata",
        "keywords",
        "entities",
        "evidence",
        "testability",
        "design",
        "datasets",
        "baselines",
        "metrics",
        "config",
        "citations",
        "figures",
        "input",
        "output",
    }
)


class Database:
    """同一套业务 SQL 跑两种后端：生产用 PostgreSQL，本地零依赖用 SQLite。"""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        url = (self.settings.database_url or "").strip()
        if url.lower().startswith(POSTGRES_SCHEMES):
            self.backend = "postgres"
            self.dsn = url
            self.path = None
        else:
            self.backend = "sqlite"
            self.path = Path(self.settings.sqlite_path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
        # SQLite 连接按线程复用：逐查询新建连接在 Windows 上开销巨大
        # （实测 3.3 万次查询 = 13 分钟，复用后 <10s）
        self._local = threading.local()

    @property
    def ph(self) -> str:
        """当前后端的参数占位符。"""
        return "%s" if self.backend == "postgres" else "?"

    # ---------- 连接 ----------
    @contextmanager
    def connection(self) -> Iterator[Any]:
        if self.backend == "postgres":
            if psycopg is None:
                raise RuntimeError("未安装 psycopg：pip install 'psycopg[binary,pool]'")
            conn = psycopg.connect(self.dsn, autocommit=True)
            try:
                yield conn
            finally:
                conn.close()
        else:
            conn = getattr(self._local, "conn", None)
            if conn is None:
                conn = sqlite3.connect(self.path)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA foreign_keys = ON")
                # WAL + NORMAL：本地单写者场景下把逐查询 commit 的 fsync 开销降到接近零
                conn.execute("PRAGMA journal_mode = WAL")
                conn.execute("PRAGMA synchronous = NORMAL")
                self._local.conn = conn
            try:
                yield conn
                conn.commit()  # 无写事务时为 no-op
            except Exception:
                conn.rollback()
                raise

    # ---------- CRUD ----------
    def execute(self, sql: str, params: Sequence[Any] | None = None) -> int:
        with self.connection() as conn:
            cur = conn.execute(sql, self._adapt(params or []))
            return cur.rowcount

    def insert(self, sql: str, params: Sequence[Any] | None = None) -> int:
        """插入一行并返回自增主键 id（跨后端）。"""
        with self.connection() as conn:
            if self.backend == "postgres":
                cur = conn.execute(sql + " RETURNING id", self._adapt(params or []))
                return int(cur.fetchone()[0])
            cur = conn.execute(sql, self._adapt(params or []))
            return int(cur.lastrowid)

    def insert_ignore(
        self, sql_rest: str, params: Sequence[Any] | None = None, conflict_cols: str = ""
    ) -> int | None:
        """插入（冲突跳过）。sql_rest 以 'INTO ...' 开头；冲突返回 None，否则返回自增 id。

        - PostgreSQL: INSERT ... ON CONFLICT (conflict_cols) DO NOTHING RETURNING id
        - SQLite: INSERT OR IGNORE ...（以 total_changes 判断是否真正插入）
        """
        with self.connection() as conn:
            if self.backend == "postgres":
                sql = f"INSERT {sql_rest} ON CONFLICT ({conflict_cols}) DO NOTHING RETURNING id"
                cur = conn.execute(sql, self._adapt(params or []))
                row = cur.fetchone()
                return int(row[0]) if row else None
            before = conn.total_changes
            cur = conn.execute(f"INSERT OR IGNORE {sql_rest}", self._adapt(params or []))
            return int(cur.lastrowid) if conn.total_changes > before else None

    def query(self, sql: str, params: Sequence[Any] | None = None) -> list[dict]:
        with self.connection() as conn:
            cur = conn.execute(sql, self._adapt(params or []))
            cols = [d[0] for d in cur.description]
            return [self._row(dict(zip(cols, row))) for row in cur.fetchall()]

    def query_one(self, sql: str, params: Sequence[Any] | None = None) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql: str, params: Sequence[Any] | None = None) -> Any:
        row = self.query_one(sql, params)
        return next(iter(row.values())) if row else None

    def healthy(self) -> bool:
        try:
            return self.scalar("SELECT 1") == 1
        except Exception as exc:
            logger.warning("数据库健康检查失败: {}", exc)
            return False

    # ---------- JSON 适配 ----------
    def dumps(self, value: Any) -> Any:
        """写入 JSON 列：pg 用 psycopg Json 适配器（保证 dict/list → jsonb），sqlite 转 JSON 字符串。"""
        if value is None:
            return None
        if self.backend == "postgres":
            from psycopg.types.json import Json

            return Json(value)
        return json.dumps(value, ensure_ascii=False)

    def _adapt(self, params: Sequence[Any]) -> list[Any] | tuple:
        if self.backend == "postgres":
            return list(params)
        return tuple(
            json.dumps(p, ensure_ascii=False) if isinstance(p, (dict, list)) else p for p in params
        )

    def _row(self, row: dict) -> dict:
        for col in JSON_COLUMNS:
            if isinstance(row.get(col), str):
                try:
                    row[col] = json.loads(row[col])
                except ValueError:
                    pass
        return row

    # ---------- 迁移 ----------
    def migrate(self, migrations_dir: Path | str | None = None) -> list[str]:
        """按顺序执行未应用的迁移，返回本次执行的版本号列表（幂等）。"""
        if migrations_dir:
            root = Path(migrations_dir)
        elif self.settings.migrations_dir:
            root = Path(self.settings.migrations_dir)
        else:
            root = Path(__file__).resolve().parents[2] / "migrations" / self.backend
        if not root.is_dir():
            raise FileNotFoundError(f"迁移目录不存在：{root}")

        create = (
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            if self.backend == "postgres"
            else "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        self.execute(create)
        applied = {r["version"] for r in self.query("SELECT version FROM schema_migrations")}

        ran: list[str] = []
        for sql_file in sorted(root.glob("*.sql")):
            if sql_file.stem in applied:
                continue
            sql = sql_file.read_text(encoding="utf-8")
            with self.connection() as conn:
                if self.backend == "sqlite":
                    conn.executescript(sql)
                else:
                    conn.execute(sql)  # psycopg 支持一次执行多条语句
            self.execute(
                f"INSERT INTO schema_migrations (version) VALUES ({self.ph})",
                [sql_file.stem],
            )
            ran.append(sql_file.stem)
            logger.info("已应用迁移 {} ({})", sql_file.stem, self.backend)
        return ran


def get_default_db() -> Database:
    return Database()
