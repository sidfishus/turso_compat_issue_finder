from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from run.cases import CheckResult


def write_summary_markdown(
    results: list[CheckResult],
    path: Path,
    *,
    triage_report: dict[str, Any] | None = None,
) -> None:
    mismatches = [result for result in results if result.diff_kind is not None]
    lines = [
        "# Compatibility report",
        "",
        f"- Total cases: {len(results)}",
        f"- Matched: {len(results) - len(mismatches)}",
        f"- Mismatches: {len(mismatches)}",
        "",
    ]

    if triage_report:
        summary = triage_report["summary"]
        lines.extend(
            [
                f"- Actionable / undocumented: {summary['actionable']}",
                "",
            ]
        )

    if not mismatches:
        lines.append("No mismatches.")
    elif triage_report:
        entries_by_id = {entry["id"]: entry for entry in triage_report["entries"]}
        priority_classes = ["undocumented", "actionable", "known_partial", "known_gap", "noise"]
        grouped: dict[str, list[CheckResult]] = defaultdict(list)
        for result in mismatches:
            entry = entries_by_id.get(result.id, {})
            triage_class = entry.get("triage_class", "actionable")
            grouped[triage_class].append(result)

        for triage_class in priority_classes:
            class_results = grouped.get(triage_class, [])
            if not class_results:
                continue
            lines.extend([f"## {triage_class.replace('_', ' ').title()} ({len(class_results)})", ""])
            by_area: dict[str, list[CheckResult]] = defaultdict(list)
            for result in class_results:
                entry = entries_by_id.get(result.id, {})
                by_area[entry.get("area", "other")].append(result)
            for area in sorted(by_area):
                lines.append(f"### {area}")
                lines.append("")
                for result in by_area[area]:
                    lines.extend(_format_case(result, entries_by_id.get(result.id)))
    else:
        lines.extend(["## Mismatches", ""])
        for result in mismatches:
            lines.extend(_format_case(result, None))

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _format_case(result: CheckResult, triage_entry: dict[str, Any] | None) -> list[str]:
    lines = [
        f"#### `{result.id}` ({result.diff_kind})",
        "",
        f"- Tags: {', '.join(result.tags)}",
        f"- SQLite: `{result.sqlite['outcome']}`",
        f"- Turso: `{result.turso['outcome']}`",
    ]
    if triage_entry:
        lines.append(f"- Triage: `{triage_entry.get('triage_class')}` — {triage_entry.get('reason', '')}")
        if triage_entry.get("compat_status"):
            lines.append(f"- COMPAT.md: `{triage_entry['compat_status']}`")
        if triage_entry.get("github_issues"):
            lines.append("- GitHub issues:")
            for issue in triage_entry["github_issues"]:
                lines.append(f"  - [{issue['title']}]({issue['url']})")
    lines.append("")
    if result.setup:
        lines.extend(["**Setup:**", "", "```sql", result.setup.rstrip(), "```", ""])
    if result.database:
        lines.append(f"- Database: `{result.database}`")
        lines.append("")
    lines.extend(["**SQL:**", "", "```sql", result.sql.rstrip(), "```", ""])
    if result.sqlite["rows"] != result.turso["rows"]:
        lines.extend(
            [
                f"- SQLite rows: `{result.sqlite['rows']}`",
                f"- Turso rows: `{result.turso['rows']}`",
                "",
            ]
        )
    return lines
