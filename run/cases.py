from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CheckCase:
    id: str
    sql: str
    tags: tuple[str, ...]
    setup: str = ""
    database: str = ""


@dataclass(frozen=True)
class CheckResult:
    id: str
    sql: str
    tags: tuple[str, ...]
    diff_kind: str | None
    sqlite: dict[str, object]
    turso: dict[str, object]
    setup: str = ""
    database: str = ""


def case_sql(case: CheckCase) -> str:
    setup = case.setup.strip()
    if setup:
        return f"{setup}\n{case.sql}"
    return case.sql
