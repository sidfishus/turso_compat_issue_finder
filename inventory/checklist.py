from __future__ import annotations

from pathlib import Path

from inventory.triage import print_triage_summary, triage_results, write_triage_report
from run.cases import CheckResult
from run.checklist import write_discrepancies_checklist
from run.reporting import write_summary_markdown
from run.store import load_results


def results_from_ledger() -> list[CheckResult]:
    stored = load_results()
    results: list[CheckResult] = []
    for row in stored.values():
        if row.get("status") != "mismatch":
            continue
        results.append(
            CheckResult(
                id=row["id"],
                sql=row["sql"],
                setup=row.get("setup", ""),
                database=row.get("database", ""),
                tags=tuple(row.get("tags", [])),
                diff_kind=row.get("diff_kind"),
                sqlite=row["sqlite"],
                turso=row["turso"],
            )
        )
    return sorted(results, key=lambda item: item.id)


def write_reports_from_ledger(
    *,
    triage_path: Path = Path("report/triage.json"),
    summary_path: Path = Path("report/summary.md"),
    checklist_csv_path: Path = Path("report/discrepancies.csv"),
    checklist_md_path: Path = Path("report/discrepancies.md"),
) -> dict[str, object]:
    results = results_from_ledger()
    triage_report = write_triage_report(results, triage_path)
    write_summary_markdown(results, summary_path, triage_report=triage_report)
    write_discrepancies_checklist(results, checklist_csv_path, triage_report=triage_report)
    write_discrepancies_checklist(results, checklist_md_path, triage_report=triage_report)
    return triage_report


def main() -> int:
    triage_report = write_reports_from_ledger()
    print_triage_summary(triage_report)
    print("triage written to report/triage.json")
    print("summary written to report/summary.md")
    print("checklist written to report/discrepancies.csv and report/discrepancies.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
