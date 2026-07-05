from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from run.cases import CheckResult


def write_discrepancies_checklist(
    results: list[CheckResult],
    path: Path,
    *,
    triage_report: dict[str, Any],
) -> None:
    mismatches = [result for result in results if result.diff_kind is not None]
    entries_by_id = {entry["id"]: entry for entry in triage_report["entries"]}

    rows: list[dict[str, str]] = []
    for result in sorted(mismatches, key=lambda item: item.id):
        entry = entries_by_id.get(result.id, {})
        rows.append(
            {
                "id": result.id,
                "diff_kind": result.diff_kind or "",
                "triage_class": str(entry.get("triage_class") or ""),
                "issue": str(entry.get("issue") or ""),
                "issue_status": str(entry.get("issue_status") or ""),
                "problem": str(entry.get("problem_id") or ""),
                "summary": _one_line(str(entry.get("problem_summary") or entry.get("reason") or "")),
                "sql": _one_line(result.sql),
            }
        )

    suffix = path.suffix.lower()
    path.parent.mkdir(parents=True, exist_ok=True)
    if suffix == ".csv":
        _write_csv(path, rows)
    else:
        _write_markdown(path, rows, triage_report["summary"])


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "id",
        "diff_kind",
        "triage_class",
        "issue",
        "issue_status",
        "problem",
        "summary",
        "sql",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_markdown(path: Path, rows: list[dict[str, str]], summary: dict[str, Any]) -> None:
    lines = [
        "# Discrepancy checklist",
        "",
        "Track sqlite3 vs tursodb mismatches. Assign cases to problems in",
        "`inventory/known_issues.yaml`, then re-triage.",
        "",
        f"- Mismatches: {summary.get('mismatches', len(rows))}",
        f"- Actionable / undocumented: {summary.get('actionable', 0)}",
        f"- Already reported: {summary.get('known_issue', 0)}",
        "",
        "| id | diff | triage | issue | status | problem | summary | sql |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        issue_cell = f"[#{row['issue']}](https://github.com/tursodatabase/turso/issues/{row['issue']})" if row["issue"] else ""
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{row['id']}`",
                    row["diff_kind"],
                    row["triage_class"] or "—",
                    issue_cell or "—",
                    row["issue_status"] or "—",
                    f"`{row['problem']}`" if row["problem"] else "—",
                    _escape_cell(row["summary"] or "—"),
                    f"`{_escape_cell(row['sql'][:120])}{'…' if len(row['sql']) > 120 else ''}`",
                ]
            )
            + " |"
        )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _escape_cell(text: str) -> str:
    return text.replace("|", "\\|")
