from __future__ import annotations

import json
import os
import re
from pathlib import Path

from generate.archive_util import clear_dir, download_file, extract_archive
from run.cases import CheckCase
from run.store import ManifestEntry, append_manifest_entries, load_manifest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BIRD_FIXTURE_ROOT = PROJECT_ROOT / "corpus" / "fixtures" / "bird"
BIRD_ZIP = BIRD_FIXTURE_ROOT / "dev.zip"

BIRD_DOWNLOAD_URL = (
    "https://huggingface.co/datasets/HAL-9001/bird-dev/resolve/main/dev.zip"
)
BIRD_SHA256 = "cdd6d19faeb45a23970b98d3ef6c40a87987c95459c2cf12076897a60cf5a630"

ATTACH_RE = re.compile(r"\battach\b", re.IGNORECASE)
DEFAULT_MAX_DB_BYTES = 50 * 1024 * 1024


def bird_root() -> Path | None:
    env = os.environ.get("TURSO_COMPAT_BIRD_DIR")
    if env:
        path = Path(env)
        return path if path.is_dir() else None
    if BIRD_FIXTURE_ROOT.is_dir():
        try:
            return _resolve_bird_data_dir(BIRD_FIXTURE_ROOT)
        except RuntimeError:
            return None
    return None


def bird_enabled() -> bool:
    return os.environ.get("TURSO_COMPAT_BIRD", "1") == "1"


def bird_limit() -> int | None:
    raw = os.environ.get("TURSO_COMPAT_BIRD_LIMIT")
    if not raw:
        return None
    return int(raw)


def max_db_bytes() -> int:
    raw = os.environ.get("TURSO_COMPAT_BIRD_MAX_DB_BYTES")
    if not raw:
        return DEFAULT_MAX_DB_BYTES
    return int(raw)


def _resolve_bird_data_dir(root: Path) -> Path:
    if (root / "dev.json").is_file():
        return root
    for nested_name in ("dev", "dev_20240627"):
        nested = root / nested_name
        if (nested / "dev.json").is_file():
            return nested
    for nested in sorted(root.iterdir()):
        if nested.is_dir() and (nested / "dev.json").is_file():
            return nested
    raise RuntimeError(f"BIRD layout not found under {root}")


def _ensure_databases(root: Path) -> None:
    db_root = root / "dev_databases"
    if db_root.is_dir() and any(db_root.rglob("*.sqlite")):
        return
    archive = root / "dev_databases.zip"
    if not archive.is_file():
        raise FileNotFoundError(f"missing BIRD databases: {archive}")
    extract_archive(archive, root)


def download_bird(*, force: bool = False) -> Path:
    BIRD_FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)
    existing = bird_root()
    if existing is not None and not force:
        _ensure_databases(_resolve_bird_data_dir(existing))
        return _resolve_bird_data_dir(existing)

    download_file(
        BIRD_DOWNLOAD_URL,
        BIRD_ZIP,
        expected_sha256=BIRD_SHA256,
        force=force,
    )
    if force and BIRD_FIXTURE_ROOT.exists():
        for child in BIRD_FIXTURE_ROOT.iterdir():
            if child.name != "dev.zip":
                if child.is_dir():
                    clear_dir(child)
                else:
                    child.unlink()
    extract_archive(BIRD_ZIP, BIRD_FIXTURE_ROOT)
    root = _resolve_bird_data_dir(BIRD_FIXTURE_ROOT)
    _ensure_databases(root)
    return root


def _normalize_sql(sql: str) -> str:
    cleaned = sql.strip().rstrip(";").lower()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _database_path(root: Path, db_id: str) -> Path | None:
    path = root / "dev_databases" / db_id / f"{db_id}.sqlite"
    return path if path.is_file() else None


def build_bird_manifest_entries(root: Path | None = None) -> list[ManifestEntry]:
    root = root or bird_root()
    if root is None:
        raise FileNotFoundError("BIRD corpus not found; run download-bird first")
    root = _resolve_bird_data_dir(root)
    _ensure_databases(root)

    rows = json.loads((root / "dev.json").read_text(encoding="utf-8"))
    entries: list[ManifestEntry] = []
    seen_queries: set[tuple[str, str]] = set()
    skipped = {"attach": 0, "missing_db": 0, "large_db": 0, "missing_query": 0}

    for row in rows:
        query = (row.get("SQL") or row.get("sql") or "").strip()
        db_id = row.get("db_id")
        question_id = row.get("question_id")
        if not query or not db_id:
            skipped["missing_query"] += 1
            continue
        if ATTACH_RE.search(query):
            skipped["attach"] += 1
            continue
        db_path = _database_path(root, db_id)
        if db_path is None:
            skipped["missing_db"] += 1
            continue
        if db_path.stat().st_size > max_db_bytes():
            skipped["large_db"] += 1
            continue
        key = (db_id, _normalize_sql(query))
        if key in seen_queries:
            continue
        seen_queries.add(key)

        suffix = question_id if question_id is not None else len(entries)
        case_id = f"bird:dev:{db_id}:{suffix}"
        entries.append(
            ManifestEntry(
                id=case_id,
                source="bird",
                sql=query if query.endswith(";") else f"{query};",
                tags=("corpus", "bird", "dev", db_id),
                database=str(db_path.resolve()),
                meta={
                    "db_id": db_id,
                    "question_id": question_id,
                    "question": row.get("question", ""),
                    "difficulty": row.get("difficulty", ""),
                },
            )
        )

    limit = bird_limit()
    if limit is not None:
        entries = entries[:limit]

    if any(skipped.values()):
        print(
            "bird ingest skips:",
            ", ".join(f"{key}={value}" for key, value in skipped.items() if value),
        )
    return entries


def ingest_bird(*, force_download: bool = False) -> int:
    root = download_bird(force=force_download)
    entries = build_bird_manifest_entries(root)
    added = append_manifest_entries(entries, "bird")
    print(f"bird manifest: {len(entries)} cases, {added} newly added at corpus/manifest/bird.jsonl")
    return added


def load_bird_cases() -> list[CheckCase]:
    if not bird_enabled():
        return []
    cases = [entry.to_check_case() for entry in load_manifest("bird")]
    limit = bird_limit()
    if limit is not None:
        cases = cases[:limit]
    return cases
