from __future__ import annotations

import os
from pathlib import Path

from generate.bird import load_bird_cases
from generate.compat_gaps import load_compat_gap_cases
from generate.reproducers import load_reproducer_cases
from generate.schemapile import load_schemapile_cases
from generate.spider import load_spider_cases
from generate.sqltest import load_sqltest_cases
from generate.sqllogictest import load_slt_cases, load_sqllogictest_cases
from run.cases import CheckCase


def corpus_enabled() -> bool:
    return os.environ.get("TURSO_COMPAT_CORPUS", "1") != "0"


def sqltest_root() -> Path | None:
    env = os.environ.get("TURSO_COMPAT_SQLTEST_DIR")
    if env:
        path = Path(env)
        return path if path.is_dir() else None
    for candidate in (
        Path("../turso/testing/sqltests"),
        Path("../../turso/testing/sqltests"),
    ):
        resolved = candidate.resolve()
        if resolved.is_dir():
            return resolved
    return None


def slt_root() -> Path | None:
    env = os.environ.get("TURSO_COMPAT_SLT_DIR")
    if env:
        path = Path(env)
        return path if path.is_dir() else None
    for candidate in (
        Path("../sqllogictest/test"),
        Path("../../sqllogictest/test"),
        Path(__file__).resolve().parent.parent / "corpus" / "fixtures" / "slt",
    ):
        resolved = candidate.resolve()
        if resolved.is_dir() and any(resolved.rglob("*.test")):
            return resolved
    return None


def sqltest_enabled() -> bool:
    return os.environ.get("TURSO_COMPAT_SQLTEST", "0") == "1"


def include_non_memory_sqltests() -> bool:
    return os.environ.get("TURSO_COMPAT_SQLTEST_FILE_DB", "0") == "1"


def sqltest_limit() -> int | None:
    raw = os.environ.get("TURSO_COMPAT_SQLTEST_LIMIT")
    if not raw:
        return None
    return int(raw)


def slt_enabled() -> bool:
    return os.environ.get("TURSO_COMPAT_SLT", "1") != "0"


def slt_limit() -> int | None:
    raw = os.environ.get("TURSO_COMPAT_SLT_LIMIT")
    if not raw:
        return None
    return int(raw)


def load_corpus_cases() -> list[CheckCase]:
    if not corpus_enabled():
        return []
    cases = load_reproducer_cases()
    if sqltest_enabled():
        root = sqltest_root()
        if root is not None:
            sqltest_cases = load_sqltest_cases(
                root,
                include_non_memory=include_non_memory_sqltests(),
            )
            limit = sqltest_limit()
            if limit is not None:
                sqltest_cases = sqltest_cases[:limit]
            cases.extend(sqltest_cases)
    if slt_enabled():
        cases.extend(load_slt_cases(slt_root(), limit=slt_limit()))
    cases.extend(load_spider_cases())
    cases.extend(load_bird_cases())
    cases.extend(load_schemapile_cases())
    cases.extend(load_compat_gap_cases())
    return cases
