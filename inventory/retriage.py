from __future__ import annotations

import json
from pathlib import Path

from inventory.triage import print_triage_summary, write_triage_report
from run.cases import CheckResult
from run.checklist import write_discrepancies_checklist
from run.reporting import write_summary_markdown


def load_results(path: Path) -> list[CheckResult]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        CheckResult(
            id=case["id"],
            sql=case["sql"],
            setup=case.get("setup", ""),
            database=case.get("database", ""),
            tags=tuple(case["tags"]),
            diff_kind=case["diff_kind"],
            sqlite=case["sqlite"],
            turso=case["turso"],
        )
        for case in payload["cases"]
    ]


def main() -> int:
    behavior_path = Path("report/behavior_diff.json")
    if not behavior_path.exists():
        raise SystemExit(f"missing {behavior_path}; run inventory.run_checks first")

    results = load_results(behavior_path)
    triage_path = Path("report/triage.json")
    summary_path = Path("report/summary.md")
    triage_report = write_triage_report(results, triage_path)
    write_summary_markdown(results, summary_path, triage_report=triage_report)
    mismatches = [result for result in results if result.diff_kind is not None]
    write_discrepancies_checklist(results, Path("report/discrepancies.csv"), triage_report=triage_report)
    write_discrepancies_checklist(results, Path("report/discrepancies.md"), triage_report=triage_report)
    print_triage_summary(triage_report)
    print(f"triage written to {triage_path}")
    print(f"summary written to {summary_path}")
    print(f"checklist written to report/discrepancies.csv and report/discrepancies.md ({len(mismatches)} mismatches in last run)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
