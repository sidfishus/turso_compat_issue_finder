from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from run.cases import CheckCase
from run.store import ManifestEntry, append_manifest_entries, load_manifest

SKIPIF = re.compile(r"^skipif\s+(\S+)\s*$", re.IGNORECASE)
ONLYIF = re.compile(r"^onlyif\s+(\S+)\s*$", re.IGNORECASE)
STATEMENT = re.compile(r"^statement\s+(ok|error)\b(.*)$", re.IGNORECASE)
QUERY = re.compile(
    r"^query(?:\s+(?P<types>[ITR]+))?(?:\s+(?P<sort>nosort|rowsort|valuesort))?(?:\s+(?P<label>label-\S+))?\s*$",
    re.IGNORECASE,
)
CONTROL = re.compile(r"^(halt|hash-threshold)\b", re.IGNORECASE)
TCL_MARKERS = ("do_test", "tester.tcl", "execsql {")
SEPARATOR = "----"
TARGET_ENGINE = "sqlite"
FILE_RESULT = re.compile(r"^<FILE>:", re.IGNORECASE)


@dataclass
class ParsedSltFile:
    path: Path
    statements: list[str] = field(default_factory=list)
    queries: list[ParsedSltQuery] = field(default_factory=list)


@dataclass
class ParsedSltQuery:
    index: int
    sql: str
    setup: str
    type_spec: str
    sort_mode: str | None
    label: str | None


def _strip_comments(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines)


def _split_records(text: str) -> list[str]:
    records: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            if current:
                records.append("\n".join(current))
                current = []
            continue
        current.append(line)
    if current:
        records.append("\n".join(current))
    return records


def _should_skip_conditionals(conditions: list[tuple[str, str]]) -> bool:
    for kind, engine in conditions:
        engine = engine.lower()
        if kind == "skipif" and engine == TARGET_ENGINE:
            return True
        if kind == "onlyif" and engine != TARGET_ENGINE:
            return True
    return False


def _normalize_sql(sql: str) -> str:
    cleaned = sql.strip()
    if cleaned.endswith(";"):
        cleaned = cleaned.rstrip(";").strip()
    return cleaned


def _join_setup(statements: list[str]) -> str:
    parts = [_normalize_sql(statement) for statement in statements if statement.strip()]
    if not parts:
        return ""
    return ";\n".join(parts) + ";"


def _parse_query_body(lines: list[str]) -> tuple[str, bool]:
    sql_lines: list[str] = []
    for line in lines:
        if line.strip() == SEPARATOR:
            return _normalize_sql("\n".join(sql_lines)), False
        if line.strip().startswith("<FILE>:"):
            return "", True
        sql_lines.append(line)
    return _normalize_sql("\n".join(sql_lines)), False


def _looks_like_tcl(text: str) -> bool:
    return any(marker in text for marker in TCL_MARKERS)


def _looks_like_slt(text: str) -> bool:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if STATEMENT.match(stripped) or QUERY.match(stripped):
            return True
    return False


def parse_sqllogictest(text: str, path: Path | None = None) -> ParsedSltFile:
    parsed = ParsedSltFile(path=path or Path("unknown.test"))
    if _looks_like_tcl(text) or not _looks_like_slt(text):
        return parsed

    setup_statements: list[str] = []
    query_index = 0

    for record in _split_records(_strip_comments(text)):
        lines = [line.rstrip() for line in record.splitlines() if line.strip()]
        if not lines:
            continue

        conditions: list[tuple[str, str]] = []
        index = 0
        while index < len(lines):
            skip_match = SKIPIF.match(lines[index].strip())
            only_match = ONLYIF.match(lines[index].strip())
            if skip_match:
                conditions.append(("skipif", skip_match.group(1)))
                index += 1
                continue
            if only_match:
                conditions.append(("onlyif", only_match.group(1)))
                index += 1
                continue
            break

        if index >= len(lines):
            continue

        header = lines[index].strip()
        body = lines[index + 1 :]
        skip = _should_skip_conditionals(conditions)

        if CONTROL.match(header):
            if header.lower().startswith("halt"):
                break
            continue

        statement_match = STATEMENT.match(header)
        if statement_match:
            kind = statement_match.group(1).lower()
            sql = _normalize_sql("\n".join(body))
            if skip or not sql:
                continue
            if kind == "ok":
                setup_statements.append(sql)
            continue

        query_match = QUERY.match(header)
        if query_match:
            sql, skip_file_result = _parse_query_body(body)
            if skip or skip_file_result or not sql:
                continue
            query_index += 1
            parsed.queries.append(
                ParsedSltQuery(
                    index=query_index,
                    sql=sql,
                    setup=_join_setup(setup_statements),
                    type_spec=query_match.group("types") or "",
                    sort_mode=query_match.group("sort"),
                    label=query_match.group("label"),
                )
            )

    return parsed


def slt_query_to_check(
    file_stem: str,
    rel_path: Path,
    query: ParsedSltQuery,
) -> CheckCase:
    tags = ["corpus", "slt"]
    if query.type_spec:
        tags.append(f"cols:{len(query.type_spec)}")
    parts = rel_path.parts
    if parts:
        tags.append(parts[0])
    return CheckCase(
        id=f"slt:{file_stem}:q{query.index}",
        sql=query.sql if query.sql.endswith(";") else f"{query.sql};",
        tags=tuple(tags),
        setup=query.setup,
    )


def load_sqllogictest_cases(
    root: Path,
    *,
    limit: int | None = None,
) -> list[CheckCase]:
    cases: list[CheckCase] = []
    for path in sorted(root.rglob("*.test")):
        rel = path.relative_to(root)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        parsed = parse_sqllogictest(text, path)
        for query in parsed.queries:
            cases.append(slt_query_to_check(path.stem, rel, query))
            if limit is not None and len(cases) >= limit:
                return cases
    return cases


def build_slt_manifest_entries(root: Path, *, limit: int | None = None) -> list[ManifestEntry]:
    entries: list[ManifestEntry] = []
    for path in sorted(root.rglob("*.test")):
        rel = path.relative_to(root)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        parsed = parse_sqllogictest(text, path)
        for query in parsed.queries:
            check = slt_query_to_check(path.stem, rel, query)
            entries.append(
                ManifestEntry(
                    id=check.id,
                    source="slt",
                    sql=check.sql,
                    setup=check.setup,
                    tags=check.tags,
                    meta={"file": rel.as_posix(), "index": query.index},
                )
            )
            if limit is not None and len(entries) >= limit:
                return entries
    return entries


def ingest_slt(root: Path, *, limit: int | None = None) -> int:
    entries = build_slt_manifest_entries(root, limit=limit)
    added = append_manifest_entries(entries, "slt")
    print(f"slt manifest: {len(entries)} cases, {added} newly added at corpus/manifest/slt.jsonl")
    return added


def load_slt_cases(root: Path | None, *, limit: int | None = None) -> list[CheckCase]:
    manifest = load_manifest("slt")
    if manifest:
        cases = [entry.to_check_case() for entry in manifest]
        if limit is not None:
            cases = cases[:limit]
        return cases
    if root is None:
        return []
    return load_sqllogictest_cases(root, limit=limit)
