from __future__ import annotations

import re
from pathlib import Path

import yaml

from run.cases import CheckCase

REPRODUCERS_PATH = Path(__file__).resolve().parent.parent / "corpus" / "reproducers.yaml"
SQL_FENCE = re.compile(r"```(?:sql)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def load_reproducer_cases(path: Path = REPRODUCERS_PATH) -> list[CheckCase]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = data.get("reproducers", [])
    cases: list[CheckCase] = []
    for entry in entries:
        case_id = entry["id"]
        tags = tuple(["corpus", "reproducer", *entry.get("tags", [])])
        setup = (entry.get("setup") or "").strip()
        sql = (entry.get("sql") or "").strip()
        if not sql and entry.get("body"):
            sql = entry["body"].strip()
        if not sql:
            continue
        if setup and not setup.endswith(";"):
            setup += ";"
        cases.append(
            CheckCase(
                id=f"repro:{case_id}",
                sql=sql,
                tags=tags,
                setup=setup,
            )
        )
    return cases


def extract_sql_from_text(text: str) -> list[str]:
    blocks = [match.group(1).strip() for match in SQL_FENCE.finditer(text)]
    if blocks:
        return [block for block in blocks if block]
    stripped = text.strip()
    return [stripped] if stripped else []


def append_reproducer(
    case_id: str,
    sql: str,
    *,
    source: str = "",
    setup: str = "",
    tags: list[str] | None = None,
    path: Path = REPRODUCERS_PATH,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    else:
        data = {"reproducers": []}
    reproducers = data.setdefault("reproducers", [])
    entry = {
        "id": case_id,
        "source": source,
        "tags": tags or [],
        "setup": setup.rstrip(),
        "sql": sql.strip(),
    }
    reproducers.append(entry)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
