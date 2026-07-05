from __future__ import annotations

from pathlib import Path

STATUS_MAP = {
    "❌ No": "no",
    "🚧 Partial": "partial",
    "✅ Yes": "yes",
}


def normalize_subject(name: str) -> str:
    name = name.strip()
    if name.startswith("PRAGMA "):
        return name[7:].split()[0].strip()
    if "(" in name:
        return name.split("(", 1)[0].strip()
    if name.endswith("()"):
        return name[:-2]
    return name


def parse_compat_md(path: Path) -> dict[str, dict[str, str]]:
    entries: dict[str, dict[str, str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 4:
            continue
        subject = parts[1]
        status = parts[2]
        if status not in STATUS_MAP:
            continue
        note = parts[3] if len(parts) > 3 else ""
        key = normalize_subject(subject)
        if not key or key.lower() in {"feature", "statement", "function", "pragma"}:
            continue
        entries[key] = {
            "status": STATUS_MAP[status],
            "note": note,
            "subject": subject,
        }
    return entries


def subject_for_case_id(case_id: str) -> str:
    if case_id.startswith("fn:"):
        return case_id.removeprefix("fn:")
    if case_id.startswith("pragma:"):
        return case_id.removeprefix("pragma:")
    if case_id.startswith("tpl:"):
        body = case_id.removeprefix("tpl:")
        return body.split(":", 1)[0]
    return case_id
