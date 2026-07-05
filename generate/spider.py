from __future__ import annotations

import json
import os
import re
import shutil
import tarfile
import zipfile
from pathlib import Path
from urllib.request import urlretrieve

from run.cases import CheckCase
from run.store import ManifestEntry, append_manifest_entries, load_manifest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SPIDER_FIXTURE_ROOT = PROJECT_ROOT / "corpus" / "fixtures" / "spider"
SPIDER_DATA_DIR = SPIDER_FIXTURE_ROOT / "spider_data"
SPIDER_ZIP = SPIDER_FIXTURE_ROOT / "spider_data.zip"

# Re-host of canonical Yale Spider bundle (CC BY-SA 4.0).
SPIDER_DOWNLOAD_URL = (
    "https://huggingface.co/datasets/HAL-9001/spider-databases/"
    "resolve/main/spider_data.zip"
)
SPIDER_SHA256 = "00636695dabed6b5f4b8328a16b13e069a2f16591d5efcce57660669c85b121b"

SPLIT_FILES = {
    "dev": "dev.json",
    "train": "train_spider.json",
}
ATTACH_RE = re.compile(r"\battach\b", re.IGNORECASE)
DEFAULT_MAX_DB_BYTES = 50 * 1024 * 1024


def spider_root() -> Path | None:
    env = os.environ.get("TURSO_COMPAT_SPIDER_DIR")
    if env:
        path = Path(env)
        return path if path.is_dir() else None
    if SPIDER_DATA_DIR.is_dir():
        return SPIDER_DATA_DIR
    return None


def spider_enabled() -> bool:
    return os.environ.get("TURSO_COMPAT_SPIDER", "1") == "1"


def spider_splits() -> list[str]:
    raw = os.environ.get("TURSO_COMPAT_SPIDER_SPLITS", "dev,train")
    return [part.strip() for part in raw.split(",") if part.strip()]


def spider_limit() -> int | None:
    raw = os.environ.get("TURSO_COMPAT_SPIDER_LIMIT")
    if not raw:
        return None
    return int(raw)


def max_db_bytes() -> int:
    raw = os.environ.get("TURSO_COMPAT_SPIDER_MAX_DB_BYTES")
    if not raw:
        return DEFAULT_MAX_DB_BYTES
    return int(raw)


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_archive(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)
        return
    if tarfile.is_tarfile(archive):
        with tarfile.open(archive) as tf:
            tf.extractall(dest)
        return
    raise RuntimeError(f"unsupported archive format: {archive}")


def _resolve_spider_data_dir(root: Path) -> Path:
    if (root / "dev.json").exists() and (root / "database").is_dir():
        return root
    nested = root / "spider_data"
    if nested.is_dir():
        return _resolve_spider_data_dir(nested)
    raise RuntimeError(f"Spider layout not found under {root}")


def download_spider(*, force: bool = False) -> Path:
    SPIDER_FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)
    data_dir = spider_root()
    if data_dir is not None and not force:
        return data_dir

    if SPIDER_ZIP.exists() and not force:
        if _sha256(SPIDER_ZIP) != SPIDER_SHA256:
            SPIDER_ZIP.unlink()
        else:
            _extract_archive(SPIDER_ZIP, SPIDER_FIXTURE_ROOT)
            return _resolve_spider_data_dir(SPIDER_FIXTURE_ROOT)

    print(f"downloading Spider corpus from {SPIDER_DOWNLOAD_URL}")
    tmp = SPIDER_ZIP.with_suffix(".zip.part")
    urlretrieve(SPIDER_DOWNLOAD_URL, tmp)
    if _sha256(tmp) != SPIDER_SHA256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("Spider download failed SHA256 check")
    tmp.replace(SPIDER_ZIP)
    if SPIDER_DATA_DIR.exists():
        shutil.rmtree(SPIDER_DATA_DIR)
    _extract_archive(SPIDER_ZIP, SPIDER_FIXTURE_ROOT)
    return _resolve_spider_data_dir(SPIDER_FIXTURE_ROOT)


def _normalize_sql(sql: str) -> str:
    cleaned = sql.strip().rstrip(";").lower()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _database_path(root: Path, db_id: str) -> Path | None:
    path = root / "database" / db_id / f"{db_id}.sqlite"
    return path if path.is_file() else None


def _load_split_entries(root: Path, split: str) -> list[dict]:
    filename = SPLIT_FILES.get(split)
    if filename is None:
        raise ValueError(f"unknown Spider split: {split}")
    path = root / filename
    if not path.is_file():
        raise FileNotFoundError(f"missing Spider split file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def build_spider_manifest_entries(root: Path | None = None) -> list[ManifestEntry]:
    root = root or spider_root()
    if root is None:
        raise FileNotFoundError("Spider corpus not found; run download-spider first")
    root = _resolve_spider_data_dir(root)

    entries: list[ManifestEntry] = []
    seen_queries: set[tuple[str, str]] = set()
    skipped = {"attach": 0, "missing_db": 0, "large_db": 0, "missing_query": 0}

    for split in spider_splits():
        for index, row in enumerate(_load_split_entries(root, split)):
            query = (row.get("query") or "").strip()
            db_id = row.get("db_id")
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

            case_id = f"spider:{split}:{db_id}:{index}"
            entries.append(
                ManifestEntry(
                    id=case_id,
                    source="spider",
                    sql=query if query.endswith(";") else f"{query};",
                    tags=("corpus", "spider", split, db_id),
                    database=str(db_path.resolve()),
                    meta={
                        "db_id": db_id,
                        "split": split,
                        "question": row.get("question", ""),
                    },
                )
            )

    limit = spider_limit()
    if limit is not None:
        entries = entries[:limit]

    if any(skipped.values()):
        print(
            "spider ingest skips:",
            ", ".join(f"{key}={value}" for key, value in skipped.items() if value),
        )
    return entries


def ingest_spider(*, force_download: bool = False) -> int:
    root = download_spider(force=force_download)
    entries = build_spider_manifest_entries(root)
    added = append_manifest_entries(entries, "spider")
    print(f"spider manifest: {len(entries)} cases, {added} newly added at corpus/manifest/spider.jsonl")
    return added


def load_spider_cases() -> list[CheckCase]:
    if not spider_enabled():
        return []
    cases = [entry.to_check_case() for entry in load_manifest("spider")]
    limit = spider_limit()
    if limit is not None:
        cases = cases[:limit]
    return cases
