from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from generate.corpus import load_corpus_cases
from generate.expand import expand_all_templates
from inventory.fetch_metadata import fetch_metadata_diff
from inventory.functions import fetch_function_catalog, generate_function_sql
from inventory.triage import print_triage_summary, write_triage_report
from run.cases import CheckCase, CheckResult, case_sql
from run.compare import CaseComparison, DiffKind, compare_exec
from run.config import Config
from run.exec import Engine, run_sql
from run.reporting import write_summary_markdown
from run.store import (
    append_result,
    filter_by_sources,
    filter_pending,
    load_results,
    parse_source_filter,
    resume_enabled,
)


def parsed_to_dict(parsed) -> dict[str, object]:
    return {
        "outcome": parsed.outcome.value,
        "rows": [list(row) for row in parsed.rows],
        "stderr": parsed.stderr.strip(),
    }


def build_function_cases(shared_names: tuple[str, ...], config: Config) -> list[CheckCase]:
    catalog = fetch_function_catalog(config)
    cases: list[CheckCase] = []
    for name in shared_names:
        entry = catalog.get(name)
        if entry is None:
            continue
        sql = generate_function_sql(entry)
        if sql is None:
            continue
        cases.append(CheckCase(id=f"fn:{name}", sql=sql, tags=("function",)))
    return cases


def build_pragma_cases(shared_names: tuple[str, ...]) -> list[CheckCase]:
    return [
        CheckCase(id=f"pragma:{name}", sql=f"PRAGMA {name};", tags=("pragma",))
        for name in shared_names
    ]


def database_for(case: CheckCase) -> str:
    return case.database or ":memory:"


def run_case(case: CheckCase, config: Config) -> CheckResult:
    sql = case_sql(case)
    database = database_for(case)
    sqlite = run_sql(Engine.SQLITE3, sql, config=config, output_mode="list", database=database)
    turso = run_sql(Engine.TURSO, sql, config=config, output_mode="list", database=database)
    comparison: CaseComparison = compare_exec(sqlite, turso)
    sqlite_dict = parsed_to_dict(comparison.sqlite)
    turso_dict = parsed_to_dict(comparison.turso)
    diff_kind = comparison.diff_kind.value if comparison.diff_kind else None
    append_result(
        case_id=case.id,
        diff_kind=diff_kind,
        sql=case.sql,
        tags=case.tags,
        setup=case.setup,
        database=case.database,
        sqlite=sqlite_dict,
        turso=turso_dict,
    )
    return CheckResult(
        id=case.id,
        sql=case.sql,
        setup=case.setup,
        database=case.database,
        tags=case.tags,
        diff_kind=diff_kind,
        sqlite=sqlite_dict,
        turso=turso_dict,
    )


def build_all_cases(config: Config, *, source_filter: set[str] | None = None) -> list[CheckCase]:
    sources = source_filter or set()
    corpus_only = sources and sources.isdisjoint({"metadata", "template", "function", "pragma"})
    if corpus_only:
        return load_corpus_cases()

    metadata = fetch_metadata_diff(config)
    cases = build_function_cases(metadata.functions.shared, config)
    cases.extend(build_pragma_cases(metadata.pragmas.shared))
    if not sources or "template" in sources or "all" in sources:
        cases.extend(expand_all_templates())
    if not sources or sources & {"spider", "bird", "schemapile", "compat", "slt", "reproducer", "sqltest", "corpus", "all"}:
        cases.extend(load_corpus_cases())
    return cases


def result_from_store(row: dict) -> CheckResult:
    return CheckResult(
        id=row["id"],
        sql=row["sql"],
        setup=row.get("setup", ""),
        database=row.get("database", ""),
        tags=tuple(row.get("tags", [])),
        diff_kind=row.get("diff_kind"),
        sqlite=row["sqlite"],
        turso=row["turso"],
    )


def run_all_checks(
    config: Config | None = None,
    *,
    source_filter: set[str] | None = None,
) -> list[CheckResult]:
    config = config or Config.from_env()
    all_cases = build_all_cases(config, source_filter=source_filter)
    scoped_cases = filter_by_sources(all_cases, source_filter)
    pending = filter_pending(scoped_cases)

    print(
        f"cases: {len(scoped_cases)} in scope, "
        f"{len(pending)} to run, "
        f"{len(scoped_cases) - len(pending)} skipped (resume={resume_enabled()})"
    )

    for index, case in enumerate(pending, start=1):
        if index == 1 or index % 100 == 0 or index == len(pending):
            print(f"  running {index}/{len(pending)}: {case.id}")
        run_case(case, config)

    stored = load_results()
    return [result_from_store(stored[case.id]) for case in scoped_cases if case.id in stored]


def write_report(results: list[CheckResult], path: Path) -> None:
    mismatches = [result for result in results if result.diff_kind is not None]
    payload = {
        "summary": {
            "total": len(results),
            "matched": len(results) - len(mismatches),
            "mismatches": len(mismatches),
            "by_diff_kind": {
                kind.value: sum(1 for result in mismatches if result.diff_kind == kind.value)
                for kind in DiffKind
            },
        },
        "cases": [asdict(result) for result in results],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def print_summary(results: list[CheckResult]) -> None:
    mismatches = [result for result in results if result.diff_kind is not None]
    print(f"checks: {len(results)} total, {len(mismatches)} mismatches")
    for result in mismatches[:50]:
        print(f"  {result.diff_kind}: {result.id}")
        if result.database:
            print(f"    database: {result.database}")
        elif result.setup:
            print("    setup: (schema preset)")
        print(f"    sql: {result.sql[:120]}{'...' if len(result.sql) > 120 else ''}")
        print(
            f"    sqlite={result.sqlite['outcome']} "
            f"turso={result.turso['outcome']}"
        )
    if len(mismatches) > 50:
        print(f"  ... and {len(mismatches) - 50} more mismatches")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run sqlite3 vs tursodb compatibility checks")
    parser.add_argument(
        "--source",
        help="Comma-separated sources: spider, bird, schemapile, compat, slt, reproducer, sqltest, metadata, template, all",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Re-run cases even if already present in state/results.jsonl",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.no_resume:
        import os

        os.environ["TURSO_COMPAT_RESUME"] = "0"

    config = Config.from_env()
    source_filter = parse_source_filter(args.source)
    results = run_all_checks(config, source_filter=source_filter)
    report_path = Path("report/behavior_diff.json")
    triage_path = Path("report/triage.json")
    summary_path = Path("report/summary.md")

    write_report(results, report_path)
    triage_report = write_triage_report(results, triage_path)
    write_summary_markdown(results, summary_path, triage_report=triage_report)
    print_summary(results)
    print_triage_summary(triage_report)
    print(f"report written to {report_path}")
    print(f"triage written to {triage_path}")
    print(f"summary written to {summary_path}")
    print(f"results ledger: state/results.jsonl")
    return 1 if triage_report["summary"]["actionable"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
