from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import Enum

from run.config import Config


class Engine(str, Enum):
    SQLITE3 = "sqlite3"
    TURSO = "tursodb"


@dataclass(frozen=True)
class ExecResult:
    stdout: str
    stderr: str
    returncode: int

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def run_sql(
    engine: Engine,
    sql: str,
    *,
    database: str = ":memory:",
    config: Config | None = None,
    output_mode: str | None = None,
) -> ExecResult:
    """Run SQL on sqlite3 or tursodb via subprocess CLI."""
    config = config or Config.from_env()

    if engine is Engine.SQLITE3:
        cmd = [str(config.sqlite3_path), "-batch"]
        if output_mode == "list":
            cmd.append("-list")
        cmd.append(database)
    elif engine is Engine.TURSO:
        cmd = [str(config.tursodb_path), "-q"]
        if output_mode == "list":
            cmd.extend(["-m", "list"])
        cmd.append(database)
    else:
        raise ValueError(f"unknown engine: {engine!r}")

    proc = subprocess.run(
        cmd,
        input=sql,
        capture_output=True,
        text=True,
    )
    return ExecResult(
        stdout=proc.stdout,
        stderr=proc.stderr,
        returncode=proc.returncode,
    )
