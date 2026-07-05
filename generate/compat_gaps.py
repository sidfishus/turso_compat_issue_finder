from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

from inventory.compat_md import normalize_subject, parse_compat_md
from run.cases import CheckCase
from run.store import ManifestEntry, append_manifest_entries, load_manifest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COMPAT_GAPS_PATH = PROJECT_ROOT / "corpus" / "compat_gaps.yaml"

SQL_SECTIONS = frozenset(
    {
        "statements",
        "pragma",
        "expressions",
        "scalar functions",
        "mathematical functions",
        "aggregate functions",
        "date and time functions",
        "json functions",
    }
)
SKIP_SECTION_MARKERS = (
    "sqlite c api",
    "vdbe",
    "journaling",
    "extensions",
    "turso-specific",
)

PRAGMA_RE = re.compile(r"^PRAGMA\s+(\S+)", re.IGNORECASE)
FUNCTION_RE = re.compile(r"^([a-zA-Z_][\w]*)\(", re.IGNORECASE)


def compat_gaps_enabled() -> bool:
    return os.environ.get("TURSO_COMPAT_COMPAT_GAPS", "1") == "1"


def compat_md_source() -> Path | None:
    env = os.environ.get("TURSO_COMPAT_COMPAT_MD")
    if env:
        path = Path(env)
        return path if path.is_file() else None
    for candidate in (Path("../turso/COMPAT.md"), Path("../../turso/COMPAT.md")):
        resolved = candidate.resolve()
        if resolved.is_file():
            return resolved
    return None


def compat_gaps_limit() -> int | None:
    raw = os.environ.get("TURSO_COMPAT_COMPAT_GAPS_LIMIT")
    if not raw:
        return None
    return int(raw)


def _load_yaml_templates() -> dict[str, dict[str, str]]:
    if not COMPAT_GAPS_PATH.is_file():
        return {}
    data = yaml.safe_load(COMPAT_GAPS_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    templates: dict[str, dict[str, str]] = {}
    for subject, payload in data.items():
        if isinstance(payload, dict):
            templates[str(subject)] = {
                "sql": str(payload.get("sql", "")).strip(),
                "setup": str(payload.get("setup", "")).strip(),
            }
    return templates


def _current_section(line: str, section: str) -> str:
    if not line.startswith("#"):
        return section
    title = line.lstrip("#").strip().lower()
    if title.startswith("pragma"):
        return "pragma"
    if "scalar functions" in title:
        return "scalar functions"
    if "mathematical functions" in title:
        return "mathematical functions"
    if "aggregate functions" in title:
        return "aggregate functions"
    if "date and time functions" in title:
        return "date and time functions"
    if "json functions" in title:
        return "json functions"
    if title == "expressions":
        return "expressions"
    if title == "statements":
        return "statements"
    return section


def _section_allowed(section: str) -> bool:
    lowered = section.lower()
    if any(marker in lowered for marker in SKIP_SECTION_MARKERS):
        return False
    return section in SQL_SECTIONS


def _gap_entries(path: Path) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    section = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        section = _current_section(line, section)
        if not _section_allowed(section):
            continue
        if not line.startswith("|"):
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 4:
            continue
        subject = parts[1]
        status = parts[2]
        if status not in {"❌ No", "🚧 Partial"}:
            continue
        if not subject or subject.lower() in {"statement", "feature", "syntax", "function", "pragma"}:
            continue
        entries.append(
            {
                "subject": subject,
                "status": "no" if status == "❌ No" else "partial",
                "section": section,
                "note": parts[3] if len(parts) > 3 else "",
            }
        )
    return entries


def _auto_sql(subject: str, section: str) -> tuple[str, str] | None:
    pragma_match = PRAGMA_RE.match(subject)
    if pragma_match or section == "pragma":
        name = normalize_subject(subject)
        return f"PRAGMA {name};", ""

    function_match = FUNCTION_RE.match(subject)
    if function_match or section.endswith("functions"):
        fn = normalize_subject(subject)
        if "(" in subject:
            inner = subject[subject.index("(") + 1 : subject.rindex(")")]
            args = inner.strip()
            if not args:
                return f"SELECT {fn}();", ""
            return f"SELECT {fn}({args});", ""
        return f"SELECT {fn}();", ""

    return None


def _case_id(subject: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", normalize_subject(subject)).strip("_").lower()
    return f"compat:{slug or 'unknown'}"


def build_compat_gap_entries(path: Path | None = None) -> list[ManifestEntry]:
    path = path or compat_md_source()
    if path is None:
        raise FileNotFoundError("COMPAT.md not found; set TURSO_COMPAT_COMPAT_MD")

    templates = _load_yaml_templates()
    entries: list[ManifestEntry] = []
    seen_ids: set[str] = set()

    for row in _gap_entries(path):
        subject = row["subject"]
        template = templates.get(subject)
        if template:
            sql = template["sql"]
            setup = template.get("setup", "")
        else:
            auto = _auto_sql(subject, row["section"])
            if auto is None:
                continue
            sql, setup = auto

        if not sql:
            continue
        case_id = _case_id(subject)
        if case_id in seen_ids:
            continue
        seen_ids.add(case_id)
        entries.append(
            ManifestEntry(
                id=case_id,
                source="compat",
                sql=sql if sql.endswith(";") else f"{sql};",
                setup=setup,
                tags=("corpus", "compat", row["status"], row["section"].replace(" ", "-")),
                meta={
                    "subject": subject,
                    "compat_status": row["status"],
                    "section": row["section"],
                    "note": row["note"],
                },
            )
        )

    limit = compat_gaps_limit()
    if limit is not None:
        entries = entries[:limit]
    return entries


def ingest_compat_gaps(*, compat_path: Path | None = None) -> int:
    entries = build_compat_gap_entries(compat_path)
    added = append_manifest_entries(entries, "compat")
    print(f"compat manifest: {len(entries)} cases, {added} newly added at corpus/manifest/compat.jsonl")
    return added


def load_compat_gap_cases() -> list[CheckCase]:
    if not compat_gaps_enabled():
        return []
    manifest = load_manifest("compat")
    if manifest:
        cases = [entry.to_check_case() for entry in manifest]
    else:
        try:
            cases = [entry.to_check_case() for entry in build_compat_gap_entries()]
        except FileNotFoundError:
            return []
    limit = compat_gaps_limit()
    if limit is not None:
        cases = cases[:limit]
    return cases
