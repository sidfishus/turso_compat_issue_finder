from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from generate.bird import bird_root, download_bird, ingest_bird, load_bird_cases
from generate.compat_gaps import compat_md_source, ingest_compat_gaps, load_compat_gap_cases
from generate.corpus import load_corpus_cases, slt_root, sqltest_enabled, sqltest_root
from generate.reproducers import REPRODUCERS_PATH, append_reproducer, extract_sql_from_text
from generate.schemapile import (
    download_schemapile,
    ingest_schemapile,
    load_schemapile_cases,
    schemapile_root,
)
from generate.spider import ingest_spider, load_spider_cases, spider_root, download_spider
from generate.sqltest import load_sqltest_cases, parse_sqltest
from generate.sqllogictest import ingest_slt, load_sqllogictest_cases, parse_sqllogictest
from run.store import load_results, status_summary


def cmd_stats(_: argparse.Namespace) -> int:
    root = sqltest_root()
    slt = slt_root()
    all_cases = load_corpus_cases()
    repro_only = [case for case in all_cases if case.id.startswith("repro:")]
    sqltest_only: list = []
    slt_only: list = []
    if root is not None:
        sqltest_only = load_sqltest_cases(root)
    if slt is not None:
        slt_only = load_sqllogictest_cases(slt)
    print(f"reproducers: {len(repro_only)} ({REPRODUCERS_PATH})")
    if not sqltest_enabled():
        print("sqltests: off (set TURSO_COMPAT_SQLTEST=1 to include in run_checks)")
    elif root is None:
        print("sqltests: 0 (set TURSO_COMPAT_SQLTEST_DIR)")
    else:
        print(f"sqltests: {len(sqltest_only)} from {root}")
    if slt is None:
        print("sqllogictest: 0 (set TURSO_COMPAT_SLT_DIR or ingest-slt)")
    else:
        print(f"sqllogictest: {len(slt_only)} from {slt}")
    spider = spider_root()
    spider_cases = load_spider_cases()
    if spider is None:
        print("spider: 0 manifest cases (run download-spider + ingest-spider)")
    else:
        print(f"spider: {len(spider_cases)} manifest cases from {spider}")
    bird = bird_root()
    bird_cases = load_bird_cases()
    if bird is None:
        print("bird: 0 manifest cases (run download-bird + ingest-bird)")
    else:
        print(f"bird: {len(bird_cases)} manifest cases from {bird}")
    schemapile = schemapile_root()
    schemapile_cases = load_schemapile_cases()
    if schemapile is None:
        print("schemapile: 0 manifest cases (run download-schemapile + ingest-schemapile)")
    else:
        print(f"schemapile: {len(schemapile_cases)} manifest cases from {schemapile}")
    compat_cases = load_compat_gap_cases()
    compat_path = compat_md_source()
    if compat_path is None:
        print("compat gaps: 0 (set TURSO_COMPAT_COMPAT_MD or ingest-compat)")
    else:
        print(f"compat gaps: {len(compat_cases)} from {compat_path}")
    print(f"corpus total: {len(all_cases)}")
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    summary = status_summary()
    results = load_results()
    print(f"manifest cases: {summary['manifest_total']}")
    print(f"results ledger: {summary['results_total']} tested")
    print(f"untested (manifest only): {summary['untested_manifest']}")
    by_source = summary["by_source"]
    if by_source:
        print("by source:")
        for source, counts in sorted(by_source.items()):
            print(
                f"  {source}: manifest={counts['manifest']} "
                f"tested={counts['tested']} match={counts['match']} mismatch={counts['mismatch']}"
            )
    mismatches = [row for row in results.values() if row.get("status") == "mismatch"]
    print(f"mismatches in ledger: {len(mismatches)}")
    for row in mismatches[:20]:
        print(f"  {row.get('diff_kind')}: {row['id']}")
    if len(mismatches) > 20:
        print(f"  ... and {len(mismatches) - 20} more")
    return 0


def cmd_download_spider(args: argparse.Namespace) -> int:
    path = download_spider(force=args.force)
    print(f"spider corpus ready at {path}")
    return 0


def cmd_ingest_spider(args: argparse.Namespace) -> int:
    if args.download or spider_root() is None:
        download_spider(force=args.force_download)
    added = ingest_spider(force_download=args.force_download)
    print(f"ingested {added} new spider manifest entries")
    return 0


def cmd_download_bird(args: argparse.Namespace) -> int:
    path = download_bird(force=args.force)
    print(f"bird corpus ready at {path}")
    return 0


def cmd_ingest_bird(args: argparse.Namespace) -> int:
    if args.download or bird_root() is None:
        download_bird(force=args.force_download)
    added = ingest_bird(force_download=args.force_download)
    print(f"ingested {added} new bird manifest entries")
    return 0


def cmd_download_schemapile(args: argparse.Namespace) -> int:
    path = download_schemapile(force=args.force)
    print(f"schemapile corpus ready at {path}")
    return 0


def cmd_ingest_schemapile(args: argparse.Namespace) -> int:
    if args.download or schemapile_root() is None:
        download_schemapile(force=args.force_download)
    added = ingest_schemapile(force_download=args.force_download)
    print(f"ingested {added} new schemapile manifest entries")
    return 0


def cmd_ingest_compat(args: argparse.Namespace) -> int:
    path = Path(args.compat_md) if args.compat_md else None
    added = ingest_compat_gaps(compat_path=path)
    print(f"ingested {added} new compat manifest entries")
    return 0


def cmd_ingest_slt(args: argparse.Namespace) -> int:
    root = Path(args.dir) if args.dir else slt_root()
    if root is None or not root.is_dir():
        print("SLT root not found; pass --dir or set TURSO_COMPAT_SLT_DIR", file=sys.stderr)
        return 1
    added = ingest_slt(root, limit=args.limit)
    print(f"ingested {added} new slt manifest entries from {root}")
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    path = Path(args.file)
    parsed = parse_sqltest(path.read_text(encoding="utf-8"), path)
    print(f"file: {path}")
    print(f"databases: {parsed.databases or ['(default)']}")
    print(f"setups: {len(parsed.setups)}")
    print(f"tests: {len(parsed.tests)}")
    for test in parsed.tests[: args.limit]:
        flags = []
        if test.skip:
            flags.append("skip")
        if test.backend:
            flags.append(f"backend={test.backend}")
        suffix = f" [{', '.join(flags)}]" if flags else ""
        print(f"  - {test.name}{suffix}")
    if len(parsed.tests) > args.limit:
        print(f"  ... and {len(parsed.tests) - args.limit} more")
    return 0


def cmd_parse_slt(args: argparse.Namespace) -> int:
    path = Path(args.file)
    parsed = parse_sqllogictest(path.read_text(encoding="utf-8"), path)
    print(f"file: {path}")
    print(f"queries: {len(parsed.queries)}")
    for query in parsed.queries[: args.limit]:
        setup_len = len(query.setup.split(";")) - 1 if query.setup else 0
        label = f" label={query.label}" if query.label else ""
        print(f"  - q{query.index} ({query.type_spec or '?'} cols, {setup_len} setup stmts{label})")
        print(f"      {query.sql[:80]}{'...' if len(query.sql) > 80 else ''}")
    if len(parsed.queries) > args.limit:
        print(f"  ... and {len(parsed.queries) - args.limit} more")
    return 0


def _issue_number(url: str) -> str | None:
    match = re.search(r"/issues/(\d+)", url)
    return match.group(1) if match else None


def cmd_import_issue(args: argparse.Namespace) -> int:
    for url in args.urls:
        number = _issue_number(url)
        if number is None:
            print(f"skip (not an issue URL): {url}", file=sys.stderr)
            continue
        proc = subprocess.run(
            ["gh", "issue", "view", number, "--repo", "tursodatabase/turso", "--json", "title,body"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            print(f"gh failed for {url}: {proc.stderr.strip()}", file=sys.stderr)
            continue
        import json

        payload = json.loads(proc.stdout)
        blocks = extract_sql_from_text(payload["body"])
        if not blocks:
            print(f"no SQL blocks in issue #{number}", file=sys.stderr)
            continue
        for index, sql in enumerate(blocks):
            case_id = f"issue-{number}" if len(blocks) == 1 else f"issue-{number}-{index + 1}"
            append_reproducer(
                case_id,
                sql,
                source=url,
                tags=["github-issue"],
            )
            print(f"added repro:{case_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Corpus extraction utilities")
    sub = parser.add_subparsers(dest="command", required=True)

    stats = sub.add_parser("stats", help="Count corpus cases")
    stats.set_defaults(func=cmd_stats)

    parse = sub.add_parser("parse", help="Parse one .sqltest file")
    parse.add_argument("file", type=Path)
    parse.add_argument("--limit", type=int, default=20)
    parse.set_defaults(func=cmd_parse)

    parse_slt = sub.add_parser("parse-slt", help="Parse one sqllogictest .test file")
    parse_slt.add_argument("file", type=Path)
    parse_slt.add_argument("--limit", type=int, default=20)
    parse_slt.set_defaults(func=cmd_parse_slt)

    import_issue = sub.add_parser("import-issue", help="Import SQL from GitHub issue bodies")
    import_issue.add_argument("urls", nargs="+")
    import_issue.set_defaults(func=cmd_import_issue)

    status = sub.add_parser("status", help="Manifest vs results checklist")
    status.set_defaults(func=cmd_status)

    download_spider = sub.add_parser("download-spider", help="Download Spider dataset (idempotent)")
    download_spider.add_argument("--force", action="store_true", help="Re-download even if present")
    download_spider.set_defaults(func=cmd_download_spider)

    ingest_spider_cmd = sub.add_parser("ingest-spider", help="Build corpus/manifest/spider.jsonl")
    ingest_spider_cmd.add_argument("--download", action="store_true", help="Download if missing")
    ingest_spider_cmd.add_argument("--force-download", action="store_true", help="Re-download dataset")
    ingest_spider_cmd.set_defaults(func=cmd_ingest_spider)

    download_bird = sub.add_parser("download-bird", help="Download BIRD dev dataset (idempotent)")
    download_bird.add_argument("--force", action="store_true", help="Re-download even if present")
    download_bird.set_defaults(func=cmd_download_bird)

    ingest_bird_cmd = sub.add_parser("ingest-bird", help="Build corpus/manifest/bird.jsonl")
    ingest_bird_cmd.add_argument("--download", action="store_true", help="Download if missing")
    ingest_bird_cmd.add_argument("--force-download", action="store_true", help="Re-download dataset")
    ingest_bird_cmd.set_defaults(func=cmd_ingest_bird)

    download_schemapile_cmd = sub.add_parser(
        "download-schemapile",
        help="Download SchemaPile permissive SQL files (idempotent)",
    )
    download_schemapile_cmd.add_argument("--force", action="store_true")
    download_schemapile_cmd.set_defaults(func=cmd_download_schemapile)

    ingest_schemapile_cmd = sub.add_parser(
        "ingest-schemapile",
        help="Build corpus/manifest/schemapile.jsonl",
    )
    ingest_schemapile_cmd.add_argument("--download", action="store_true")
    ingest_schemapile_cmd.add_argument("--force-download", action="store_true")
    ingest_schemapile_cmd.set_defaults(func=cmd_ingest_schemapile)

    ingest_compat_cmd = sub.add_parser(
        "ingest-compat",
        help="Build corpus/manifest/compat.jsonl from COMPAT.md gaps",
    )
    ingest_compat_cmd.add_argument("--compat-md", help="Path to COMPAT.md")
    ingest_compat_cmd.set_defaults(func=cmd_ingest_compat)

    ingest_slt_cmd = sub.add_parser("ingest-slt", help="Build corpus/manifest/slt.jsonl from .test files")
    ingest_slt_cmd.add_argument("--dir", help="Path to sqllogictest test root")
    ingest_slt_cmd.add_argument("--limit", type=int, help="Cap cases ingested")
    ingest_slt_cmd.set_defaults(func=cmd_ingest_slt)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
