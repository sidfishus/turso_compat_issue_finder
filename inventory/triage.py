from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from inventory.compat_md import parse_compat_md, subject_for_case_id
from inventory.github_issues import issues_for_case
from inventory.known_issues import CaseIssueLink, load_known_issues
from run.cases import CheckResult

TAG_TO_AREA = {
    "function": "function",
    "pragma": "pragma",
    "create": "ddl",
    "index": "ddl",
    "alter": "ddl",
    "ddl": "ddl",
    "insert": "dml",
    "update": "dml",
    "delete": "dml",
    "dml": "dml",
    "select": "select",
    "join": "select",
    "aggregate": "select",
    "corpus": "corpus",
    "sqltest": "corpus",
    "slt": "corpus",
    "spider": "corpus",
    "bird": "corpus",
    "schemapile": "corpus",
    "compat": "corpus",
    "reproducer": "corpus",
}

SKIP_LIST_PATH = Path(__file__).resolve().parent / "skip_list.yaml"


@dataclass(frozen=True)
class TriageEntry:
    id: str
    area: str
    triage_class: str
    reason: str
    compat_status: str | None
    compat_note: str | None
    diff_kind: str
    sql: str
    setup: str
    tags: tuple[str, ...]
    github_issues: tuple[dict[str, str], ...] = ()
    problem_id: str | None = None
    issue: int | None = None
    issue_url: str | None = None
    issue_status: str | None = None
    problem_summary: str | None = None


def load_skip_list(path: Path = SKIP_LIST_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return dict(data.get("noise", {}))


def primary_area(tags: tuple[str, ...], case_id: str) -> str:
    if case_id.startswith("fn:"):
        return "function"
    if case_id.startswith("pragma:"):
        return "pragma"
    for tag in tags:
        if tag in TAG_TO_AREA:
            return TAG_TO_AREA[tag]
    return "other"


def compat_md_path() -> Path | None:
    env = os.environ.get("TURSO_COMPAT_COMPAT_MD")
    if not env:
        return None
    path = Path(env)
    return path if path.exists() else None


def github_search_enabled() -> bool:
    return os.environ.get("TURSO_COMPAT_GITHUB_SEARCH", "1") != "0"


def classify_result(
    result: CheckResult,
    *,
    skip_list: dict[str, str],
    compat_entries: dict[str, dict[str, str]],
    case_issues: dict[str, CaseIssueLink],
    fetch_github: bool,
) -> TriageEntry:
    subject = subject_for_case_id(result.id)
    compat = compat_entries.get(subject)
    compat_status = compat["status"] if compat else None
    compat_note = compat["note"] if compat else None
    known = case_issues.get(result.id)

    if known is not None:
        triage_class = "known_issue" if known.issue_status == "open" else "known_issue_closed"
        reason = known.summary or f"Tracked under #{known.issue}"
    elif result.id in skip_list:
        triage_class = "noise"
        reason = skip_list[result.id]
    elif compat_status == "no":
        triage_class = "known_gap"
        reason = compat_note or "Documented as unsupported in COMPAT.md"
    elif compat_status == "partial":
        triage_class = "known_partial"
        reason = compat_note or "Documented as partial in COMPAT.md"
    elif compat_status == "yes":
        triage_class = "undocumented"
        reason = "COMPAT.md claims full support; mismatch may be a new bug"
    else:
        triage_class = "actionable"
        reason = "No COMPAT.md entry; worth investigating"

    github_issues: tuple[dict[str, str], ...] = ()
    if fetch_github and triage_class in {"actionable", "undocumented"}:
        github_issues = tuple(issues_for_case(result.id))

    return TriageEntry(
        id=result.id,
        area=primary_area(result.tags, result.id),
        triage_class=triage_class,
        reason=reason,
        compat_status=compat_status,
        compat_note=compat_note,
        diff_kind=result.diff_kind or "",
        sql=result.sql,
        setup=result.setup,
        tags=result.tags,
        github_issues=github_issues,
        problem_id=known.problem_id if known else None,
        issue=known.issue if known else None,
        issue_url=known.issue_url if known else None,
        issue_status=known.issue_status if known else None,
        problem_summary=known.summary if known else None,
    )


def triage_results(
    results: list[CheckResult],
    *,
    fetch_github: bool | None = None,
) -> list[TriageEntry]:
    mismatches = [result for result in results if result.diff_kind is not None]
    skip_list = load_skip_list()
    _, case_issues = load_known_issues()
    compat_path = compat_md_path()
    compat_entries = parse_compat_md(compat_path) if compat_path else {}
    if fetch_github is None:
        fetch_github = github_search_enabled()

    return [
        classify_result(
            result,
            skip_list=skip_list,
            compat_entries=compat_entries,
            case_issues=case_issues,
            fetch_github=fetch_github,
        )
        for result in mismatches
    ]


def build_triage_report(entries: list[TriageEntry]) -> dict[str, object]:
    by_area: dict[str, list[dict[str, object]]] = defaultdict(list)
    by_class: dict[str, list[dict[str, object]]] = defaultdict(list)
    serialized = [asdict(entry) for entry in entries]

    for entry_dict in serialized:
        by_area[entry_dict["area"]].append(entry_dict)
        by_class[entry_dict["triage_class"]].append(entry_dict)

    actionable_count = sum(
        1
        for entry in entries
        if entry.triage_class in {"actionable", "undocumented"}
    )
    known_issue_count = sum(
        1 for entry in entries if entry.triage_class == "known_issue"
    )

    return {
        "summary": {
            "mismatches": len(entries),
            "actionable": actionable_count,
            "known_issue": known_issue_count,
            "by_area": {area: len(items) for area, items in sorted(by_area.items())},
            "by_triage_class": {
                triage_class: len(items)
                for triage_class, items in sorted(by_class.items())
            },
        },
        "by_area": dict(by_area),
        "by_triage_class": dict(by_class),
        "entries": serialized,
    }


def write_triage_report(results: list[CheckResult], path: Path) -> dict[str, object]:
    entries = triage_results(results)
    report = build_triage_report(entries)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def print_triage_summary(report: dict[str, object]) -> None:
    summary = report["summary"]
    print(
        f"triage: {summary['mismatches']} mismatches, "
        f"{summary['actionable']} actionable/undocumented, "
        f"{summary.get('known_issue', 0)} already reported"
    )
    by_class = summary["by_triage_class"]
    for triage_class, count in sorted(by_class.items()):
        print(f"  {triage_class}: {count}")
    print("  by area:", ", ".join(f"{k}={v}" for k, v in sorted(summary["by_area"].items())))
