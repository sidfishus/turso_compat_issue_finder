from __future__ import annotations

from dataclasses import dataclass

from run.config import Config
from run.exec import Engine, run_sql

NONDETERMINISTIC = frozenset(
    {
        "random",
        "randomblob",
        "datetime",
        "unixepoch",
        "julianday",
        "glob",
    }
)

AGGREGATE_NAMES = frozenset(
    {
        "count",
        "sum",
        "avg",
        "min",
        "max",
        "group_concat",
        "total",
        "total_changes",
        "json_group_array",
        "json_group_object",
        "jsonb_group_array",
        "jsonb_group_object",
    }
)

JSON_SCALAR_NAMES = frozenset(
    {
        "json",
        "json_array",
        "json_array_length",
        "json_extract",
        "json_insert",
        "json_object",
        "json_patch",
        "json_remove",
        "json_replace",
        "json_set",
        "json_type",
        "json_valid",
        "jsonb",
        "jsonb_array",
        "jsonb_array_length",
        "jsonb_extract",
        "jsonb_insert",
        "jsonb_object",
        "jsonb_patch",
        "jsonb_remove",
        "jsonb_replace",
        "jsonb_set",
        "jsonb_type",
        "jsonb_valid",
    }
)


@dataclass(frozen=True)
class FunctionEntry:
    name: str
    ftype: str
    nargs: int


def parse_function_entries(stdout: str) -> list[FunctionEntry]:
    entries: list[FunctionEntry] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) < 5:
            continue
        try:
            nargs = int(parts[4])
        except ValueError:
            continue
        entries.append(FunctionEntry(name=parts[0], ftype=parts[2], nargs=nargs))
    return entries


def pick_function_entry(entries: list[FunctionEntry]) -> FunctionEntry | None:
    if not entries:
        return None
    scalars = [entry for entry in entries if entry.ftype == "s"]
    if scalars:
        return min(scalars, key=lambda entry: (entry.nargs if entry.nargs >= 0 else 99, entry.nargs))
    return min(entries, key=lambda entry: (entry.nargs if entry.nargs >= 0 else 99, entry.nargs))


def fetch_function_catalog(config: Config, engine: Engine = Engine.SQLITE3) -> dict[str, FunctionEntry]:
    result = run_sql(engine, "PRAGMA function_list;", config=config, output_mode="list")
    if not result.ok:
        raise RuntimeError(
            f"{engine.value} PRAGMA function_list failed (exit {result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )

    grouped: dict[str, list[FunctionEntry]] = {}
    for entry in parse_function_entries(result.stdout):
        grouped.setdefault(entry.name, []).append(entry)

    catalog: dict[str, FunctionEntry] = {}
    for name, entries in grouped.items():
        picked = pick_function_entry(entries)
        if picked is not None:
            catalog[name] = picked
    return catalog


def literal_args(nargs: int, *, name: str = "") -> str:
    if name in JSON_SCALAR_NAMES:
        pool = ("'{}'", "'$.a'", "'1'")
    else:
        pool = ("1", "'a'", "2")
    if nargs == 0:
        return ""
    if nargs == -1:
        return ", ".join(pool[:2])
    return ", ".join(pool[:nargs])


def column_args(nargs: int) -> str:
    if nargs == 0:
        return "*"
    if nargs == -1:
        return "c1, c2"
    cols = [f"c{i + 1}" for i in range(nargs)]
    return ", ".join(cols)


def from_subquery(select_expr: str) -> str:
    return (
        f"SELECT {select_expr} "
        "FROM (SELECT 1 AS c1, 2 AS c2, 'a' AS c3);"
    )


def generate_function_sql(entry: FunctionEntry) -> str | None:
    if entry.name in NONDETERMINISTIC:
        return None

    name = entry.name
    args = literal_args(entry.nargs, name=name)
    cols = column_args(entry.nargs)

    if entry.ftype == "s":
        return f"SELECT {name}({args});"

    if entry.ftype == "a":
        return from_subquery(f"{name}({cols})")

    if name in AGGREGATE_NAMES:
        if name == "count" and entry.nargs == 0:
            return from_subquery("count(*)")
        return from_subquery(f"{name}({cols})")

    if entry.nargs == 0:
        return f"SELECT {name}() OVER (ORDER BY 1);"
    return f"SELECT {name}({args}) OVER (ORDER BY 1);"
