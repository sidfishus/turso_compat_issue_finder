from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from generate.archive_util import clear_dir, download_file, extract_archive
from run.cases import CheckCase
from run.store import ManifestEntry, append_manifest_entries, load_manifest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMAPILE_FIXTURE_ROOT = PROJECT_ROOT / "corpus" / "fixtures" / "schemapile"
SCHEMAPILE_TAR = SCHEMAPILE_FIXTURE_ROOT / "schemapile-perm-sqlfiles.tar.gz"
SCHEMAPILE_SQL_ROOT = SCHEMAPILE_FIXTURE_ROOT / "sqlfiles_permissive"

SCHEMAPILE_DOWNLOAD_URL = (
    "https://zenodo.org/records/12682521/files/schemapile-perm-sqlfiles.tar.gz"
)
SCHEMAPILE_SHA256 = "48924077bd97a1f6811d9f90a92cac2175451958fcab4b62067d72888b31ec68"

CREATE_RE = re.compile(
    r"^\s*create\s+(?:unique\s+)?(?:virtual\s+)?(?:temp\s+)?"
    r"(?:table|index|view|trigger)\b",
    re.IGNORECASE,
)
SKIP_MARKERS = (
    "engine=",
    "auto_increment",
    "serial not null",
    "set names ",
    "set foreign_key_checks",
    "drop database",
    "create database",
    "create sequence",
    "create or replace package",
    "create user ",
    "grant ",
    "delimiter ",
    "use `",
    "use ",
    "begin\n",
    "pl/sql",
    "number(",
    "varchar2(",
    "nvarchar2(",
    "clob",
    "blob(",
    "identity(",
    "on update current_timestamp",
)
DEFAULT_LIMIT = 5000
DEFAULT_MAX_STMT_BYTES = 8192
DEFAULT_MAX_FILE_BYTES = 256 * 1024


def schemapile_root() -> Path | None:
    env = os.environ.get("TURSO_COMPAT_SCHEMAPILE_DIR")
    if env:
        path = Path(env)
        return path if path.is_dir() else None
    if SCHEMAPILE_SQL_ROOT.is_dir():
        return SCHEMAPILE_SQL_ROOT
    return None


def schemapile_enabled() -> bool:
    return os.environ.get("TURSO_COMPAT_SCHEMAPILE", "1") == "1"


def schemapile_limit() -> int | None:
    raw = os.environ.get("TURSO_COMPAT_SCHEMAPILE_LIMIT")
    if not raw:
        return DEFAULT_LIMIT
    return int(raw)


def max_stmt_bytes() -> int:
    raw = os.environ.get("TURSO_COMPAT_SCHEMAPILE_MAX_STMT_BYTES")
    if not raw:
        return DEFAULT_MAX_STMT_BYTES
    return int(raw)


def max_file_bytes() -> int:
    raw = os.environ.get("TURSO_COMPAT_SCHEMAPILE_MAX_FILE_BYTES")
    if not raw:
        return DEFAULT_MAX_FILE_BYTES
    return int(raw)


def download_schemapile(*, force: bool = False) -> Path:
    SCHEMAPILE_FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)
    existing = schemapile_root()
    if existing is not None and not force:
        return existing

    download_file(
        SCHEMAPILE_DOWNLOAD_URL,
        SCHEMAPILE_TAR,
        expected_sha256=SCHEMAPILE_SHA256,
        force=force,
    )
    if force and SCHEMAPILE_SQL_ROOT.exists():
        clear_dir(SCHEMAPILE_SQL_ROOT)
    extract_archive(SCHEMAPILE_TAR, SCHEMAPILE_FIXTURE_ROOT)
    if not SCHEMAPILE_SQL_ROOT.is_dir():
        raise RuntimeError(f"SchemaPile layout not found under {SCHEMAPILE_FIXTURE_ROOT}")
    return SCHEMAPILE_SQL_ROOT


def _split_sql_statements(text: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    for line in text.splitlines():
        stripped = line.strip()
        if not in_single and not in_double and stripped.startswith("--"):
            continue
        current.append(line)
        for index, char in enumerate(line):
            if char == "'" and not in_double:
                if in_single and index + 1 < len(line) and line[index + 1] == "'":
                    continue
                in_single = not in_single
            elif char == '"' and not in_single:
                in_double = not in_double
        if not in_single and not in_double and stripped.endswith(";"):
            statement = "\n".join(current).strip()
            current = []
            if statement:
                statements.append(statement)
    tail = "\n".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def _looks_sqlite_compatible(statement: str) -> bool:
    lowered = statement.lower()
    if not CREATE_RE.match(statement):
        return False
    if len(statement.encode("utf-8")) > max_stmt_bytes():
        return False
    if any(marker in lowered for marker in SKIP_MARKERS):
        return False
    return True


def _normalize_statement(statement: str) -> str:
    cleaned = statement.strip().rstrip(";")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.lower()


def _statement_id(file_stem: str, index: int, statement: str) -> str:
    digest = hashlib.sha256(statement.encode("utf-8")).hexdigest()[:10]
    return f"schemapile:{file_stem}:{index}:{digest}"


def build_schemapile_manifest_entries(root: Path | None = None) -> list[ManifestEntry]:
    root = root or schemapile_root()
    if root is None:
        raise FileNotFoundError("SchemaPile corpus not found; run download-schemapile first")

    entries: list[ManifestEntry] = []
    seen: set[str] = set()
    skipped = {"file_large": 0, "not_create": 0, "dialect": 0}

    for path in sorted(root.rglob("*.sql")):
        if path.stat().st_size > max_file_bytes():
            skipped["file_large"] += 1
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = path.relative_to(root)
        file_stem = rel.as_posix().replace("/", "__").removesuffix(".sql")
        for index, statement in enumerate(_split_sql_statements(text)):
            if not CREATE_RE.match(statement):
                skipped["not_create"] += 1
                continue
            if not _looks_sqlite_compatible(statement):
                skipped["dialect"] += 1
                continue
            normalized = _normalize_statement(statement)
            if normalized in seen:
                continue
            seen.add(normalized)
            sql = statement if statement.rstrip().endswith(";") else f"{statement.rstrip()};"
            entries.append(
                ManifestEntry(
                    id=_statement_id(file_stem, index, normalized),
                    source="schemapile",
                    sql=sql,
                    tags=("corpus", "schemapile", "ddl"),
                    meta={"file": rel.as_posix(), "index": index},
                )
            )
            limit = schemapile_limit()
            if limit is not None and len(entries) >= limit:
                break
        limit = schemapile_limit()
        if limit is not None and len(entries) >= limit:
            break

    if any(skipped.values()):
        print(
            "schemapile ingest skips:",
            ", ".join(f"{key}={value}" for key, value in skipped.items() if value),
        )
    return entries


def ingest_schemapile(*, force_download: bool = False) -> int:
    root = download_schemapile(force=force_download)
    entries = build_schemapile_manifest_entries(root)
    added = append_manifest_entries(entries, "schemapile")
    print(
        f"schemapile manifest: {len(entries)} cases, {added} newly added "
        "at corpus/manifest/schemapile.jsonl"
    )
    return added


def load_schemapile_cases() -> list[CheckCase]:
    if not schemapile_enabled():
        return []
    cases = [entry.to_check_case() for entry in load_manifest("schemapile")]
    limit = schemapile_limit()
    if limit is not None:
        cases = cases[:limit]
    return cases
