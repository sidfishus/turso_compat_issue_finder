from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from run.exec import ExecResult


class Outcome(str, Enum):
    OK = "ok"
    ERROR = "error"


class DiffKind(str, Enum):
    OUTCOME_MISMATCH = "outcome_mismatch"
    ERROR_MESSAGE_MISMATCH = "error_message_mismatch"
    RESULT_MISMATCH = "result_mismatch"
    STDERR_MISMATCH = "stderr_mismatch"


@dataclass(frozen=True)
class ParsedResult:
    outcome: Outcome
    rows: tuple[tuple[str, ...], ...]
    stderr: str


@dataclass(frozen=True)
class CaseComparison:
    diff_kind: DiffKind | None
    sqlite: ParsedResult
    turso: ParsedResult


def parse_list_output(result: ExecResult) -> ParsedResult:
    if result.ok:
        rows = tuple(
            tuple(cell for cell in line.split("|"))
            for line in result.stdout.splitlines()
            if line.strip()
        )
        return ParsedResult(Outcome.OK, rows, result.stderr)
    return ParsedResult(Outcome.ERROR, (), result.stderr)


def normalize_stderr(stderr: str) -> str:
    return stderr.replace("\r\n", "\n").strip()


def compare_parsed(sqlite: ParsedResult, turso: ParsedResult) -> CaseComparison:
    if sqlite.outcome is not turso.outcome:
        return CaseComparison(DiffKind.OUTCOME_MISMATCH, sqlite, turso)
    if sqlite.outcome is Outcome.ERROR:
        if normalize_stderr(sqlite.stderr) != normalize_stderr(turso.stderr):
            return CaseComparison(DiffKind.ERROR_MESSAGE_MISMATCH, sqlite, turso)
        return CaseComparison(None, sqlite, turso)
    if sqlite.rows != turso.rows:
        return CaseComparison(DiffKind.RESULT_MISMATCH, sqlite, turso)
    if normalize_stderr(sqlite.stderr) != normalize_stderr(turso.stderr):
        return CaseComparison(DiffKind.STDERR_MISMATCH, sqlite, turso)
    return CaseComparison(None, sqlite, turso)


def compare_exec(sqlite: ExecResult, turso: ExecResult) -> CaseComparison:
    return compare_parsed(parse_list_output(sqlite), parse_list_output(turso))
