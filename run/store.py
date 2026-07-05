from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from run.cases import CheckCase

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_DIR = PROJECT_ROOT / "corpus" / "manifest"
RESULTS_PATH = PROJECT_ROOT / "state" / "results.jsonl"


def manifest_path(source: str) -> Path:
    return MANIFEST_DIR / f"{source}.jsonl"


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


@dataclass(frozen=True)
class ManifestEntry:
    id: str
    source: str
    sql: str
    tags: tuple[str, ...]
    setup: str = ""
    database: str = ""
    meta: dict | None = None

    def to_check_case(self) -> CheckCase:
        return CheckCase(
            id=self.id,
            sql=self.sql,
            tags=self.tags,
            setup=self.setup,
            database=self.database,
        )

    def to_dict(self) -> dict:
        payload = {
            "id": self.id,
            "source": self.source,
            "sql": self.sql,
            "tags": list(self.tags),
            "setup": self.setup,
            "database": self.database,
        }
        if self.meta:
            payload["meta"] = self.meta
        return payload

    @classmethod
    def from_dict(cls, data: dict) -> ManifestEntry:
        return cls(
            id=data["id"],
            source=data["source"],
            sql=data["sql"],
            tags=tuple(data.get("tags", [])),
            setup=data.get("setup", ""),
            database=data.get("database", ""),
            meta=data.get("meta"),
        )


def load_manifest(source: str | None = None) -> list[ManifestEntry]:
    if source is not None:
        paths = [manifest_path(source)]
    else:
        if not MANIFEST_DIR.exists():
            return []
        paths = sorted(MANIFEST_DIR.glob("*.jsonl"))
    entries: list[ManifestEntry] = []
    seen: set[str] = set()
    for path in paths:
        for row in read_jsonl(path):
            entry = ManifestEntry.from_dict(row)
            if entry.id in seen:
                continue
            seen.add(entry.id)
            entries.append(entry)
    return entries


def manifest_ids(source: str | None = None) -> set[str]:
    return {entry.id for entry in load_manifest(source)}


def append_manifest_entries(entries: list[ManifestEntry], source: str) -> int:
    path = manifest_path(source)
    existing = manifest_ids(source)
    added = 0
    for entry in entries:
        if entry.id in existing:
            continue
        append_jsonl(path, entry.to_dict())
        existing.add(entry.id)
        added += 1
    return added


def load_completed_ids() -> set[str]:
    return {row["id"] for row in read_jsonl(RESULTS_PATH) if "id" in row}


def load_results() -> dict[str, dict]:
    results: dict[str, dict] = {}
    for row in read_jsonl(RESULTS_PATH):
        if "id" in row:
            results[row["id"]] = row
    return results


def append_result(
    *,
    case_id: str,
    diff_kind: str | None,
    sql: str,
    tags: tuple[str, ...],
    setup: str,
    database: str,
    sqlite: dict,
    turso: dict,
) -> None:
    status = "match" if diff_kind is None else "mismatch"
    append_jsonl(
        RESULTS_PATH,
        {
            "id": case_id,
            "status": status,
            "diff_kind": diff_kind,
            "sql": sql,
            "setup": setup,
            "database": database,
            "tags": list(tags),
            "sqlite": sqlite,
            "turso": turso,
            "tested_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def resume_enabled() -> bool:
    return os.environ.get("TURSO_COMPAT_RESUME", "1") != "0"


def filter_pending(cases: list[CheckCase]) -> list[CheckCase]:
    if not resume_enabled():
        return cases
    completed = load_completed_ids()
    return [case for case in cases if case.id not in completed]


def case_sources(case: CheckCase) -> set[str]:
    sources: set[str] = set()
    for tag in case.tags:
        if tag in {"spider", "bird", "schemapile", "compat", "slt", "sqltest", "reproducer"}:
            sources.add(tag)
    if case.id.startswith("fn:") or case.id.startswith("pragma:"):
        sources.add("metadata")
    if case.id.startswith("tpl:"):
        sources.add("template")
    if case.id.startswith("repro:"):
        sources.add("reproducer")
    if case.id.startswith("slt:"):
        sources.add("slt")
    if case.id.startswith("sqltest:"):
        sources.add("sqltest")
    if case.id.startswith("spider:"):
        sources.add("spider")
    if case.id.startswith("bird:"):
        sources.add("bird")
    if case.id.startswith("schemapile:"):
        sources.add("schemapile")
    if case.id.startswith("compat:"):
        sources.add("compat")
    return sources


def filter_by_sources(cases: list[CheckCase], sources: set[str] | None) -> list[CheckCase]:
    if not sources or "all" in sources:
        return cases
    return [case for case in cases if case_sources(case) & sources]


def parse_source_filter(raw: str | None) -> set[str] | None:
    if not raw:
        env = os.environ.get("TURSO_COMPAT_SOURCE")
        raw = env
    if not raw:
        return None
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def status_summary() -> dict[str, object]:
    manifest = load_manifest()
    results = load_results()
    by_source: dict[str, dict[str, int]] = {}
    for entry in manifest:
        bucket = by_source.setdefault(entry.source, {"manifest": 0, "tested": 0, "match": 0, "mismatch": 0})
        bucket["manifest"] += 1
        result = results.get(entry.id)
        if result:
            bucket["tested"] += 1
            if result.get("status") == "match":
                bucket["match"] += 1
            else:
                bucket["mismatch"] += 1
    return {
        "manifest_total": len(manifest),
        "results_total": len(results),
        "untested_manifest": sum(1 for entry in manifest if entry.id not in results),
        "by_source": by_source,
    }
