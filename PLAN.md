# Turso ↔ SQLite compatibility finder

Standalone tool (this repo). Run locally; not intended for upstream merge into
[tursodatabase/turso](https://github.com/tursodatabase/turso).

**Goal:** Automate discovery of behavioral differences between `sqlite3` and
`tursodb` by generating SQL from templates and introspection, running both
engines, and reporting structured diffs suitable for triage and contribution
picking.

**Non-goals (for now):**

- CI integration or Turso repo coupling
- Full grammar fuzzing (Turso already has `testing/differential-oracle/`)
- Exact error-message matching
- MVCC / experimental Turso features

---

## Core insight

**Keywords are inventory, not test units.** SQLite has ~147 reserved words, but
most (`WHEN`, `THEN`, `BY`, `AND`) only appear inside valid grammar contexts.
Do not generate `SELECT {keyword}` per keyword.

Instead:

1. **Introspection lists** — runtime metadata both engines expose
2. **Statement templates** — grammar skeletons with fillable slots
3. **Slot fillers** — literals, columns, expressions, function calls
4. **Schema presets** — empty / one-table / join / trigger contexts
5. **Compare** — outcome + results (not raw stdout equality)

---

## What SQLite exposes

### Keywords

- **No SQL query** for the keyword list
- **C API:** `sqlite3_keyword_count()`, `sqlite3_keyword_name()`,
  `sqlite3_keyword_check()` — runtime list for the linked lib
- **Static list:** [sqlite.org/lang_keywords.html](https://www.sqlite.org/lang_keywords.html)
  — vend as `inventory/keywords.txt`; optional ctypes helper to verify against
  local sqlite3

Use keywords for **coverage tracking** (“did we exercise `RECURSIVE` in a valid
`WITH RECURSIVE`?”), not primary generation.

### Better runtime lists (high value)

Both engines support these via CLI:

```sql
PRAGMA function_list;   -- name, pure, type, nargs, flags, ...
PRAGMA pragma_list;     -- supported pragma names
```

**First-pass compat scan:** diff `function_list` and `pragma_list` between
sqlite3 and tursodb. Already surfaces real gaps (e.g. window fns in sqlite3,
array fns in Turso extensions).

Optional: `PRAGMA compile_options` to skip tests for features the local sqlite3
was not built with.

---

## SQL template strategy

### Layer 1 — Statement skeletons (~30–50 hand-written)

Organized by grammar, not by keyword. Examples:

```sql
SELECT {expr} FROM {table};
SELECT {expr} FROM {table} WHERE {pred};
SELECT {expr} FROM {table} ORDER BY {col};
INSERT INTO {table} VALUES ({literals});
UPDATE {table} SET {col}={expr} WHERE {pred};
CREATE TABLE {t} ({col_defs});
CREATE INDEX {i} ON {t}({cols});
CREATE TRIGGER {tr} {timing} {event} ON {t} BEGIN {body} END;
ALTER TABLE {t} RENAME COLUMN {old} TO {new};
SELECT * FROM t1 {join_kind} JOIN t2 ON {pred};
WITH {cte} AS ({select}) SELECT * FROM {cte};
SELECT {expr} OVER (PARTITION BY {col} ORDER BY {col});
PRAGMA {name};
PRAGMA {name}({arg});
```

Store as YAML/JSON: template id, required schema preset, slot definitions,
tags (e.g. `window`, `alter`, `pragma`).

### Layer 2 — Slot fillers

| Slot        | Source                                      |
|-------------|---------------------------------------------|
| `{expr}`    | literals, column refs, `func(args)`, CASE   |
| `{pred}`    | comparisons, AND/OR, IN, BETWEEN, IS NULL |
| `{col_defs}`| types, PK, UNIQUE, CHECK, NOT NULL        |
| `{func}`    | from shared `function_list` entries         |
| `{pragma}`  | from shared `pragma_list` entries           |

### Layer 3 — Schema presets

Fixed starting states (fresh temp DB per case or reset script):

- `empty`
- `one_table` — `CREATE TABLE t(a INT, b TEXT); INSERT …`
- `two_table` — for JOIN tests
- `with_index`, `with_trigger`, `with_view` — composed from setup SQL

### Layer 4 — Corpus extraction (later)

- Turso `.sqltest` `@query` blocks
- GitHub `label:compatibility` issue reproducers
- COMPAT.md ❌ / 🚧 rows as targeted templates

---

## Comparison semantics

| Dimension              | Match required? | Notes                                      |
|------------------------|-----------------|--------------------------------------------|
| Success vs error       | **Yes**         | Core compat signal                         |
| Result set values      | **Yes**         | Multiset compare if no `ORDER BY`          |
| Row count              | **Yes**         |                                            |
| Error message text     | No              | Turso accepts semantic parity              |
| Column order/names     | Maybe           | Configurable                               |
| Shell dot-commands     | Separate track  | CLI compat, not SQL engine                 |
| Turso-only functions   | Skip            | Flag separately, not as sqlite regressions |
| Nondeterministic fns   | Skip            | `random()`, `datetime('now')`, etc.        |

**Diff kinds:** `result_mismatch`, `outcome_mismatch`, `parse_error`,
`exec_error`, `timeout`, `panic`

Reference: Turso's `scripts/diff.sh` compares stdout only and treats errors as
always-fail — this tool should implement **outcome parity** explicitly.

---

## Architecture (proposed)

```
turso_compat_issue_finder/
  PLAN.md                 # this file
  inventory/
    keywords.txt          # vendored from sqlite.org
    fetch_metadata.py     # PRAGMA function_list / pragma_list from both engines
  templates/
    select.yaml
    ddl.yaml
    dml.yaml
    pragma.yaml
  generate/
    expand.py             # template × fillers × schemas → SQL scripts
  run/
    exec.py               # subprocess sqlite3 + tursodb
    compare.py            # outcome + result comparison
  report/
    # written at run time: diff_report.json, summary.md
  corpus/                 # optional extracted SQL (later)
```

**Engine invocation:** subprocess CLI (`sqlite3`, `tursodb`) for simplicity and
fidelity to real user behavior. Configurable paths via env or CLI flags.

**Output:** JSON records `{id, sql, setup, tags, sqlite, turso, diff_kind}` plus
human-readable markdown summary.

---

## Phases

### Phase 0 — Scaffold

- [ ] Repo layout, `pyproject.toml` or minimal Python package
- [ ] Config: paths to `sqlite3`, `tursodb`, temp dir
- [ ] `exec.py`: run multi-statement SQL on `:memory:` or temp file DB
- [ ] `compare.py`: outcome parity + multiset row compare

### Phase 1 — Metadata diff (quick win)

- [ ] `fetch_metadata.py`: run `PRAGMA function_list` / `pragma_list` on both
- [ ] Diff report: only-in-sqlite3, only-in-turso, in-both
- [ ] For **shared functions**, auto-generate `SELECT fn(minimal_args)` cases
- [ ] For **shared pragmas**, try safe read-only forms

### Phase 2 — Template expansion

- [ ] YAML template format (skeleton + slots + schema preset + tags)
- [ ] Initial set: SELECT, INSERT, UPDATE, CREATE TABLE, CREATE INDEX, PRAGMA
- [ ] Slot fillers: literals, simple exprs, function calls from shared list
- [ ] JSON report + markdown summary

### Phase 3 — Triage helpers

- [ ] Tag failures by area (pragma, ddl, function, dml)
- [ ] Optional: cross-ref open GitHub issues by SQL fingerprint / tags
- [ ] Optional: skip list from COMPAT.md known gaps (reduce noise)

### Phase 4 — Corpus (optional)

- [ ] Extract `@query` from Turso `.sqltest` files
- [ ] Import issue reproducers from clipboard/URL list

---

## Pitfalls

1. **Invalid SQL explosion** — use grammar-aware templates, not keyword combos
2. **Known gaps** — filter or tag against COMPAT.md to avoid rediscovering window fns daily
3. **Side effects** — isolate DB per case (temp files or fresh `:memory:`)
4. **Extensions** — Turso-only builtins are not sqlite regressions
5. **Noise budget** — start narrow (metadata + functions + 10 templates), widen later

---

## Existing Turso tooling (reference, don't duplicate)

| Tool | Location | Use |
|------|----------|-----|
| Quick diff | `scripts/diff.sh` | Manual one-liner compare |
| Differential oracle | `testing/differential-oracle/` | Schema-aware random SQL + compare |
| Fuzz tests | `tests/fuzz/` | Area-specific differential tests |
| SQLancer | `scripts/run-sqlancer.sh` | External query oracle |
| Compat checklist | `COMPAT.md` | Known ❌ / 🚧 status |

This repo fills the gap: **contributor-facing, local, structured triage** from
templates + introspection — not a new fuzzer.

---

## Open decisions

- **Language:** Python for orchestration (ctypes for keyword API if needed)
- **Template format:** YAML vs JSON — YAML likely easier to edit by hand
- **DB mode:** `:memory:` default; file DBs for ATTACH / VACUUM later
- **Parallelism:** serial first; parallel case runs later
- **Issue linking:** manual vs `gh` API — defer to Phase 3

---

## First milestone (target: 1–2 sessions)

1. Metadata diff (`function_list`, `pragma_list`)
2. Auto `SELECT func(...)` for every function in the intersection
3. Ten hand-written DDL/DML templates
4. JSON report with `diff_kind` per case

Success = running one command produces a list of reproducible diffs you can
inspect before picking a Turso issue to fix.
