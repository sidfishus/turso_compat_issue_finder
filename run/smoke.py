from __future__ import annotations

import sys

from run.config import Config
from run.exec import Engine, run_sql


def main() -> int:
    config = Config.from_env()
    sql = "SELECT 1;"

    for engine in (Engine.SQLITE3, Engine.TURSO):
        result = run_sql(engine, sql, config=config)
        print(f"{engine.value}: exit={result.returncode}")
        if result.stdout:
            print(result.stdout.rstrip())
        if result.stderr:
            print(result.stderr.rstrip(), file=sys.stderr)

        if not result.ok or "1" not in result.stdout:
            print(f"smoke failed for {engine.value}", file=sys.stderr)
            return 1

    print("smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
