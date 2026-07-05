from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from run.config import Config
from run.exec import Engine, run_sql


@dataclass(frozen=True)
class NameDiff:
    shared: tuple[str, ...]
    sqlite3_only: tuple[str, ...]
    turso_only: tuple[str, ...]


@dataclass(frozen=True)
class MetadataDiff:
    functions: NameDiff
    pragmas: NameDiff


def parse_function_list(stdout: str) -> set[str]:
    names: set[str] = set()
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        names.add(line.split("|", 1)[0])
    return names


def parse_pragma_list(stdout: str) -> set[str]:
    return {line.strip() for line in stdout.splitlines() if line.strip()}


def diff_names(sqlite3_names: set[str], turso_names: set[str]) -> NameDiff:
    return NameDiff(
        shared=tuple(sorted(sqlite3_names & turso_names)),
        sqlite3_only=tuple(sorted(sqlite3_names - turso_names)),
        turso_only=tuple(sorted(turso_names - sqlite3_names)),
    )


def fetch_function_names(engine: Engine, config: Config) -> set[str]:
    result = run_sql(engine, "PRAGMA function_list;", config=config, output_mode="list")
    if not result.ok:
        raise RuntimeError(
            f"{engine.value} PRAGMA function_list failed (exit {result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return parse_function_list(result.stdout)


def fetch_pragma_names(engine: Engine, config: Config) -> set[str]:
    result = run_sql(engine, "PRAGMA pragma_list;", config=config, output_mode="list")
    if not result.ok:
        raise RuntimeError(
            f"{engine.value} PRAGMA pragma_list failed (exit {result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return parse_pragma_list(result.stdout)


def fetch_metadata_diff(config: Config | None = None) -> MetadataDiff:
    config = config or Config.from_env()
    sqlite3_functions = fetch_function_names(Engine.SQLITE3, config)
    turso_functions = fetch_function_names(Engine.TURSO, config)
    sqlite3_pragmas = fetch_pragma_names(Engine.SQLITE3, config)
    turso_pragmas = fetch_pragma_names(Engine.TURSO, config)
    return MetadataDiff(
        functions=diff_names(sqlite3_functions, turso_functions),
        pragmas=diff_names(sqlite3_pragmas, turso_pragmas),
    )


def write_report(diff: MetadataDiff, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(diff), indent=2) + "\n", encoding="utf-8")


def print_summary(diff: MetadataDiff) -> None:
    for label, name_diff in (("functions", diff.functions), ("pragmas", diff.pragmas)):
        print(f"{label}:")
        print(f"  shared:       {len(name_diff.shared)}")
        print(f"  sqlite3 only: {len(name_diff.sqlite3_only)}")
        print(f"  turso only:   {len(name_diff.turso_only)}")
        if name_diff.sqlite3_only:
            print(f"  sqlite3 only: {', '.join(name_diff.sqlite3_only)}")
        if name_diff.turso_only:
            print(f"  turso only:   {', '.join(name_diff.turso_only)}")
        print()


def main() -> int:
    config = Config.from_env()
    diff = fetch_metadata_diff(config)
    report_path = Path("report/metadata_diff.json")
    write_report(diff, report_path)
    print_summary(diff)
    print(f"report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
