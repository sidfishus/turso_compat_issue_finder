from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any

import yaml

from run.cases import CheckCase

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
SKIP_TEMPLATE_FILES = frozenset({"schemas.yaml", "fillers.yaml"})


def load_schemas(templates_dir: Path = TEMPLATES_DIR) -> dict[str, str]:
    path = templates_dir / "schemas.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    schemas = data.get("schemas", {})
    return {name: (value or "").strip() for name, value in schemas.items()}


def load_template_files(templates_dir: Path = TEMPLATES_DIR) -> list[dict[str, Any]]:
    templates: list[dict[str, Any]] = []
    for path in sorted(templates_dir.glob("*.yaml")):
        if path.name in SKIP_TEMPLATE_FILES:
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        templates.extend(data.get("templates", []))
    return templates


def fill_slots(sql: str, slot_values: dict[str, str]) -> str:
    filled = sql
    for slot, value in slot_values.items():
        filled = filled.replace(f"{{{slot}}}", value)
    return filled


def expand_template(
    template: dict[str, Any],
    schemas: dict[str, str],
) -> list[CheckCase]:
    schema_name = template["schema"]
    if schema_name not in schemas:
        raise KeyError(f"unknown schema preset {schema_name!r} for template {template['id']!r}")

    setup = schemas[schema_name]
    tags = tuple(template.get("tags", []))
    slot_sets: dict[str, list[str]] = template.get("slot_sets", {})
    base_id = f"tpl:{template['id']}"

    if not slot_sets:
        return [
            CheckCase(
                id=base_id,
                sql=template["sql"].strip(),
                tags=tags,
                setup=setup,
            )
        ]

    keys = list(slot_sets.keys())
    value_lists = [slot_sets[key] for key in keys]
    cases: list[CheckCase] = []
    for index, combo in enumerate(itertools.product(*value_lists)):
        slot_values = dict(zip(keys, combo))
        sql = fill_slots(template["sql"], slot_values)
        cases.append(
            CheckCase(
                id=f"{base_id}:{index}",
                sql=sql.strip(),
                tags=tags,
                setup=setup,
            )
        )
    return cases


def expand_all_templates(templates_dir: Path = TEMPLATES_DIR) -> list[CheckCase]:
    schemas = load_schemas(templates_dir)
    cases: list[CheckCase] = []
    for template in load_template_files(templates_dir):
        cases.extend(expand_template(template, schemas))
    return cases
