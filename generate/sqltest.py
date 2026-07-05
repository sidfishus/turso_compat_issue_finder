from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from run.cases import CheckCase

SKIP_IF_MVCC = re.compile(r"^@skip-if\s+mvcc\b", re.IGNORECASE)
SKIP_FILE = re.compile(r"^@skip-file\b", re.IGNORECASE)
SKIP_FILE_IF_MVCC = re.compile(r"^@skip-file-if\s+mvcc\b", re.IGNORECASE)
AT_SETUP = re.compile(r"^@setup\s+(\w+)\s*$")
AT_BACKEND = re.compile(r"^@backend\s+(\w+)\s*$", re.IGNORECASE)
AT_DATABASE = re.compile(r"^@database\s+(\S+)(?:\s+readonly)?\s*$", re.IGNORECASE)
BLOCK_HEADER = re.compile(
    r"^(setup|test|expect(?:\s+\w+)?|@?snapshot(?:-eqp)?)\s+([\w.-]+)?\s*\{?\s*$",
    re.IGNORECASE,
)

QUERY_PREFIXES = ("select", "with", "pragma", "explain", "values")


@dataclass
class ParsedSqltest:
    path: Path
    databases: list[str] = field(default_factory=list)
    setups: dict[str, str] = field(default_factory=dict)
    skip_file: bool = False
    tests: list[ParsedSqltestCase] = field(default_factory=list)


@dataclass
class ParsedSqltestCase:
    name: str
    body: str
    setup_names: tuple[str, ...]
    skip: bool = False
    backend: str | None = None


def _find_block_end(text: str, start: int, *, initial_depth: int = 0) -> int:
    depth = initial_depth
    in_single = False
    in_double = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if in_single or in_double:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError("unclosed block")


def _read_block(lines: list[str], start: int) -> tuple[str, str, int]:
    header = lines[start].strip()
    open_brace = header.find("{")
    if open_brace >= 0:
        header_prefix = header[:open_brace]
        first_body = header[open_brace + 1 :]
        initial_depth = 1
    else:
        header_prefix = header
        first_body = ""
        initial_depth = 0

    match = BLOCK_HEADER.match(header_prefix.strip())
    if not match:
        raise ValueError(f"not a block header: {header!r}")
    kind = match.group(1).lower()
    name = (match.group(2) or "").strip()

    body_parts = [first_body]
    line_index = start + 1
    while line_index < len(lines):
        body_parts.append(lines[line_index])
        candidate = "\n".join(body_parts)
        try:
            end = _find_block_end(candidate, 0, initial_depth=initial_depth)
        except ValueError:
            line_index += 1
            continue
        body = candidate[:end].strip()
        trailing = candidate[end + 1 :].strip()
        if trailing:
            raise ValueError(f"unexpected trailing content after block: {trailing!r}")
        return kind, name, body, line_index + 1

    raise ValueError(f"unclosed block starting at line {start + 1}")


def _split_statements(sql: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    escape = False
    for char in sql:
        if escape:
            current.append(char)
            escape = False
            continue
        if char == "\\":
            current.append(char)
            escape = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            current.append(char)
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            current.append(char)
            continue
        if char == ";" and not in_single and not in_double:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            continue
        current.append(char)
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def _split_setup_and_query(body: str) -> tuple[str, str]:
    statements = _split_statements(body)
    if not statements:
        return "", ""
    if len(statements) == 1:
        return "", statements[0]
    last = statements[-1].lstrip()
    if last.lower().startswith(QUERY_PREFIXES):
        setup = ";\n".join(statements[:-1])
        if setup:
            setup += ";"
        return setup, statements[-1]
    combined = ";\n".join(statements)
    if combined and not combined.endswith(";"):
        combined += ";"
    return "", combined


def _memory_compatible(databases: list[str]) -> bool:
    if not databases:
        return True
    return all(db.strip().lower() == ":memory:" for db in databases)


def parse_sqltest(text: str, path: Path | None = None) -> ParsedSqltest:
    parsed = ParsedSqltest(path=path or Path("unknown.sqltest"))
    lines = text.splitlines()
    index = 0
    pending_setups: list[str] = []
    pending_skip = False
    pending_backend: str | None = None

    while index < len(lines):
        raw = lines[index]
        line = raw.strip()
        if not line or line.startswith("#"):
            index += 1
            continue

        if SKIP_FILE.match(line) or SKIP_FILE_IF_MVCC.match(line):
            parsed.skip_file = True
            index += 1
            continue

        db_match = AT_DATABASE.match(line)
        if db_match:
            parsed.databases.append(db_match.group(1))
            index += 1
            continue

        setup_match = AT_SETUP.match(line)
        if setup_match:
            pending_setups.append(setup_match.group(1))
            index += 1
            continue

        if SKIP_IF_MVCC.match(line):
            pending_skip = True
            index += 1
            continue

        if line.lower().startswith("@skip-if sqlite"):
            index += 1
            continue

        backend_match = AT_BACKEND.match(line)
        if backend_match:
            pending_backend = backend_match.group(1).lower()
            index += 1
            continue

        if line.startswith("@cross-check-integrity") or line.startswith("@requires"):
            index += 1
            continue

        if not BLOCK_HEADER.match(line.split("{", 1)[0].strip()):
            index += 1
            continue

        try:
            kind, name, body, next_index = _read_block(lines, index)
        except ValueError:
            index += 1
            continue

        index = next_index
        if kind == "setup":
            parsed.setups[name] = body
            continue
        if kind.startswith("expect"):
            pending_setups = []
            pending_skip = False
            pending_backend = None
            continue
        if kind.startswith("snapshot") or kind.startswith("@snapshot"):
            pending_setups = []
            pending_skip = False
            pending_backend = None
            continue
        if kind == "test":
            parsed.tests.append(
                ParsedSqltestCase(
                    name=name,
                    body=body,
                    setup_names=tuple(pending_setups),
                    skip=pending_skip,
                    backend=pending_backend,
                )
            )
            pending_setups = []
            pending_skip = False
            pending_backend = None

    return parsed


def sqltest_case_to_check(
    file_stem: str,
    rel_path: Path,
    test: ParsedSqltestCase,
    setups: dict[str, str],
) -> CheckCase:
    setup_parts = [setups[name] for name in test.setup_names if name in setups]
    body_setup, query = _split_setup_and_query(test.body)
    if body_setup:
        setup_parts.append(body_setup)
    setup = ";\n".join(part.strip().rstrip(";") for part in setup_parts if part.strip())
    if setup:
        setup += ";"
    tags = ["corpus", "sqltest"]
    parts = rel_path.parts
    if parts:
        tags.append(parts[0])
    return CheckCase(
        id=f"sqltest:{file_stem}:{test.name}",
        sql=query or test.body.strip(),
        tags=tuple(tags),
        setup=setup,
    )


def load_sqltest_cases(
    root: Path,
    *,
    include_non_memory: bool = False,
) -> list[CheckCase]:
    cases: list[CheckCase] = []
    for path in sorted(root.rglob("*.sqltest")):
        rel = path.relative_to(root)
        try:
            parsed = parse_sqltest(path.read_text(encoding="utf-8"), path)
        except ValueError:
            continue
        if parsed.skip_file:
            continue
        if not _memory_compatible(parsed.databases) and not include_non_memory:
            continue
        for test in parsed.tests:
            if test.skip:
                continue
            if test.backend is not None and test.backend != "cli":
                continue
            cases.append(
                sqltest_case_to_check(path.stem, rel, test, parsed.setups),
            )
    return cases
