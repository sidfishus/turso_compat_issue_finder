"""Find the next compatibility discrepancy to file and prep issue drafts."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from inventory.checklist import results_from_ledger
from inventory.triage import TriageEntry, triage_results
from run.compare import compare_exec
from run.config import Config
from run.exec import Engine, run_sql

TRIAGE_PRIORITY = {
    "undocumented": 0,
    "actionable": 1,
}

DIFF_KIND_PRIORITY = {
    "outcome_mismatch": 0,
    "error_message_mismatch": 1,
    "result_mismatch": 2,
    "stderr_mismatch": 3,
}

CASE_ID_PREFIX_PRIORITY = {
    "fn:": 0,
    "pragma:": 1,
    "compat:": 2,
    "tpl:": 3,
    "repro:": 4,
}


@dataclass(frozen=True)
class ScoredCandidate:
    entry: TriageEntry
    score: tuple[int, ...]

    @property
    def case_id(self) -> str:
        return self.entry.id


def _case_prefix_rank(case_id: str) -> int:
    for prefix, rank in CASE_ID_PREFIX_PRIORITY.items():
        if case_id.startswith(prefix):
            return rank
    return 10


def score_candidate(entry: TriageEntry) -> tuple[int, ...]:
    return (
        TRIAGE_PRIORITY.get(entry.triage_class, 99),
        DIFF_KIND_PRIORITY.get(entry.diff_kind, 99),
        _case_prefix_rank(entry.id),
        len(entry.id),
        entry.id,
    )


def list_candidates(*, limit: int = 10, fetch_github: bool = True) -> list[ScoredCandidate]:
    entries = triage_results(results_from_ledger(), fetch_github=fetch_github)
    candidates = [
        ScoredCandidate(entry=entry, score=score_candidate(entry))
        for entry in entries
        if entry.triage_class in {"actionable", "undocumented"}
    ]
    candidates.sort(key=lambda item: item.score)
    return candidates[:limit]


def format_candidate(candidate: ScoredCandidate, *, index: int | None = None) -> str:
    entry = candidate.entry
    prefix = f"{index}. " if index is not None else ""
    gh = ""
    if entry.github_issues:
        links = ", ".join(f"#{issue['number']}" for issue in entry.github_issues[:3])
        gh = f"\n   github: {links}"
    return (
        f"{prefix}{entry.id} ({entry.triage_class}, {entry.diff_kind})\n"
        f"   reason: {entry.reason}\n"
        f"   sql: {entry.sql[:120]}{'…' if len(entry.sql) > 120 else ''}"
        f"{gh}"
    )


def combined_sql(entry: TriageEntry) -> str:
    setup = entry.setup.strip()
    if setup:
        return f"{setup}\n{entry.sql}"
    return entry.sql


def run_repro(entry: TriageEntry, *, config: Config | None = None) -> dict[str, object]:
    config = config or Config.from_env()
    sql = combined_sql(entry)
    database = ":memory:"

    sqlite_exec = run_sql(
        Engine.SQLITE3, sql, config=config, output_mode="list", database=database
    )
    turso_exec = run_sql(
        Engine.TURSO, sql, config=config, output_mode="list", database=database
    )
    comparison = compare_exec(sqlite_exec, turso_exec)
    return {
        "case_id": entry.id,
        "sql": entry.sql,
        "setup": entry.setup,
        "sqlite": comparison.sqlite,
        "turso": comparison.turso,
        "diff_kind": comparison.diff_kind.value if comparison.diff_kind else None,
        "outcome_match": comparison.sqlite.outcome == comparison.turso.outcome,
    }


def search_github_queries(queries: list[str], *, limit: int = 5) -> list[dict[str, str]]:
    seen: set[str] = set()
    results: list[dict[str, str]] = []
    for query in queries:
        try:
            proc = subprocess.run(
                [
                    "gh",
                    "search",
                    "issues",
                    "--repo",
                    "tursodatabase/turso",
                    query,
                    "--limit",
                    str(limit),
                    "--json",
                    "number,title,state,url",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode != 0:
            continue
        try:
            issues = json.loads(proc.stdout)
        except json.JSONDecodeError:
            continue
        for issue in issues:
            url = issue["url"]
            if url in seen:
                continue
            seen.add(url)
            results.append(
                {
                    "number": str(issue["number"]),
                    "title": issue["title"],
                    "state": issue.get("state", ""),
                    "url": url,
                    "query": query,
                }
            )
    return results


def default_search_queries(entry: TriageEntry) -> list[str]:
    subject = entry.id.split(":", 1)[-1].replace("_", " ")
    queries = [
        subject,
        f"{subject} compatibility",
        entry.sql[:80],
    ]
    if entry.id.startswith("fn:"):
        fn = entry.id.removeprefix("fn:")
        queries.extend(
            [
                f"{fn} odd number of arguments",
                f"{fn} sqlite",
            ]
        )
    return queries


def draft_slug(entry: TriageEntry) -> str:
    name = entry.id.replace(":", "-").replace("/", "-")
    return name


def issues_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "issues"


def existing_draft_path(entry: TriageEntry) -> Path | None:
    directory = issues_dir()
    if not directory.exists():
        return None
    for path in sorted(directory.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        if entry.id in text or f"`{entry.id}`" in text:
            return path
    return None


def cmd_candidates(args: argparse.Namespace) -> int:
    candidates = list_candidates(limit=args.limit, fetch_github=not args.no_github)
    if not candidates:
        print("No actionable or undocumented mismatches in the ledger.")
        return 1
    print(f"Top {len(candidates)} candidate(s):\n")
    for index, candidate in enumerate(candidates, start=1):
        print(format_candidate(candidate, index=index))
        draft = existing_draft_path(candidate.entry)
        if draft:
            print(f"   draft: {draft}")
        print()
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    candidates = list_candidates(limit=1, fetch_github=not args.no_github)
    if not candidates:
        print("No actionable or undocumented mismatches in the ledger.")
        return 1
    candidate = candidates[0]
    entry = candidate.entry
    print(format_candidate(candidate))
    draft = existing_draft_path(entry)
    if draft:
        print(f"\nExisting draft: {draft}")
    if args.repro:
        print("\n=== Repro ===")
        repro = run_repro(entry)
        for engine in ("sqlite", "turso"):
            result = repro[engine]
            print(f"\n{engine}:")
            print(f"  outcome: {result.outcome.value}")
            if result.stderr:
                print(f"  stderr: {result.stderr.strip()}")
            if result.rows:
                print(f"  rows: {list(result.rows)}")
        print(f"\ndiff_kind: {repro['diff_kind']}")
        print(f"outcome_match: {repro['outcome_match']}")
    if args.search:
        print("\n=== GitHub search ===")
        queries = default_search_queries(entry)
        for query in queries:
            print(f"  query: {query!r}")
        issues = search_github_queries(queries, limit=args.search_limit)
        if not issues:
            print("  (no matches)")
        for issue in issues:
            state = issue.get("state", "")
            print(f"  #{issue['number']} [{state}] {issue['title']}")
            print(f"    {issue['url']}  (via {issue['query']!r})")
    suggested = issues_dir() / f"{draft_slug(entry)}.md"
    print(f"\nSuggested draft path: {suggested}")
    print("Run skill `turso-compat-issue-draft` to write the markdown draft.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Find the next Turso compatibility discrepancy to file.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    candidates = sub.add_parser("candidates", help="List ranked filing candidates")
    candidates.add_argument("--limit", type=int, default=10)
    candidates.add_argument("--no-github", action="store_true")
    candidates.set_defaults(func=cmd_candidates)

    nxt = sub.add_parser("next", help="Show top candidate with optional repro/search")
    nxt.add_argument("--repro", action="store_true", help="Run sqlite3 vs tursodb")
    nxt.add_argument("--search", action="store_true", help="Search GitHub for duplicates")
    nxt.add_argument("--search-limit", type=int, default=5)
    nxt.add_argument("--no-github", action="store_true")
    nxt.set_defaults(func=cmd_next)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
