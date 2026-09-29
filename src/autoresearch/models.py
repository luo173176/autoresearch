"""领域模型的轻量封装（数据库行字典 → 类型化对象），随阶段逐步充实。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Project:
    id: int
    name: str
    question: str
    domain: str
    budget: dict
    status: str
    created_at: str | None = None

    @classmethod
    def from_row(cls, row: dict) -> "Project":
        return cls(**{k: row[k] for k in cls.__dataclass_fields__ if k in row})


@dataclass
class Paper:
    id: int
    title: str
    authors: list
    year: int | None = None
    venue: str | None = None
    abstract: str | None = None
    url: str | None = None
    pdf_path: str | None = None
    dedupe_key: str | None = None
    metadata: dict | None = None
