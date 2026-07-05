# Turso ↔ SQLite compatibility finder

Standalone tool (this repo). Run locally; not intended for upstream merge into
[tursodatabase/turso](https://github.com/tursodatabase/turso).

**Goal:** Automate discovery of behavioral differences between `sqlite3` and
`tursodb` by generating SQL from templates and introspection, running both
engines through the **same comparison algorithm**, and recording **any**
difference as a potential compatibility issue for triage and contribution
picking.

**Comparison stance:** alert on everything first; tune false positives later
via `inventory/skip_list.yaml` and COMPAT.md classification once patterns are
known — not by silently ignoring diff dimensions up front.

**Non-goals (for now):**

- CI integration or Turso repo coupling
- Full grammar fuzzing (Turso already has `testing/differential-oracle/`)
- MVCC / experimental Turso features
- **Any automatic GitHub posting** — see [GitHub interaction policy](#github-interaction-policy) below

---

## GitHub interaction policy

**Never automatically post to GitHub.** This tool helps you find, triage, and
prepare compatibility findings so *you* can decide what to file upstream. It must
not create issues, comments, PRs, or any other GitHub content on your behalf.

Allowed GitHub usage (read-only / local prep only):

- **`import-issue`** — pull SQL reproducers *from* an existing issue URL into
  `corpus/reproducers.yaml` (ingest for re-testing, not posting)
- **`github_issues.py`** — optional `gh search issues` cross-ref in triage
  reports (links only; disable with `TURSO_COMPAT_GITHUB_SEARCH=0`)

Out of scope permanently unless you explicitly change this policy in the plan:

- `gh issue create`, `gh pr create`, commenting, labeling, or any automated
  filing workflow
- Agents or scripts that open Turso issues from mismatch reports without your
  manual review and explicit command

You triage locally (`report/summary.md`, `report/triage.json`); you file issues
when and how you choose.

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

### Layer 4 — Corpus extraction

Harvest SQL from existing sources instead of generating everything from scratch:

| Source | Format | Status | Notes |
|--------|--------|--------|-------|
| Turso `.sqltest` | `test { … }` blocks | **opt-in** | Parser kept; off by default — Turso CI already runs these against sqlite3 + tursodb |
| Issue reproducers | YAML / `import-issue` | **done** | `corpus/reproducers.yaml` |
| **SQLite sqllogictest** | `.test` DSL | **infra done** | Parser + manifest ingest; 2 sample cases ingested — run `ingest-slt --dir …` for full corpus |
| Text-to-SQL benchmarks | JSON + schema | **spider + bird done** | Spider train+dev; BIRD dev → manifests |
| GitHub DDL crawls | SQL in repos | **schemapile done** | SchemaPile-Perm SQL files → DDL manifest |
| Stack Overflow dump | free-text + SQL | **skipped** | Noisy; not planned |
| Turso TCL conformance | `do_test` / `execsql` | not planned | Different format from sqllogictest |
| COMPAT.md ❌ / 🚧 rows | targeted templates | **done** | `corpus/compat_gaps.yaml` + auto PRAGMA cases |

#### External SQL corpora (reference)

**Integrated (manifest + resumable checks):**

1. **[Spider](https://yale-lily.github.io/spider)** — train+dev text-to-SQL; 4,483 manifest cases with per-`db_id` file DBs.
2. **[BIRD](https://bird-bench.github.io/)** — dev split; 917 manifest cases (612 skipped at ingest for DBs > 50MB).
3. **[SchemaPile-Perm](https://zenodo.org/records/8270251)** — GitHub DDL crawl; 5,000 filtered `CREATE` statements (SQLite-compatible, size-capped).
4. **COMPAT.md ❌ / 🚧 rows** — 230 targeted cases from `corpus/compat_gaps.yaml` + auto PRAGMA generation.
5. **[SQLite sqllogictest corpus](https://www.sqlite.org/sqllogictest/)** — parser + manifest ingest done; only 2 sample cases ingested so far. Full corpus: clone or extract via [sqlite-sqllogictest-corpus](https://github.com/jzombie/sqlite-sqllogictest-corpus), then `ingest-slt --dir …`. Skips TCL regression tests (`do_test`, `tester.tcl`).
6. **GitHub issue reproducers** — `import-issue <url>` → `corpus/reproducers.yaml`.

**Not useful for discovery (opt-in only):**

- **Turso `.sqltest`** — Turso CI already runs these on `tursodb` and `sqlite3`. Parser + `parse` CLI remain; set `TURSO_COMPAT_SQLTEST=1` to include in checks.

**Not integrated:**

- **Stack Overflow data dump** — skipped; noisy, multi-dialect.
- **DuckDB sqllogictest-inspired tests** — same DSL; not wired up.
- **Turso TCL conformance** (`do_test` / `execsql`) — different format from sqllogictest.
- **gitschemas** and other schema crawls — SchemaPile covers DDL for now.

---

## Comparison semantics

For each case, run the same SQL against the same database (or setup + SQL on
`:memory:`) on both engines, parse both outputs the same way, and diff
everything observable. Any mismatch is recorded; triage later decides priority.

| Dimension              | Match required? | Notes                                      |
|------------------------|-----------------|--------------------------------------------|
| Success vs error       | **Yes**         | `outcome_mismatch`                         |
| Error message text     | **Yes**         | When both error — `error_message_mismatch` |
| Result rows            | **Yes**         | Strict ordered compare (`-list` output)    |
| Row/column order       | **Yes**         | Part of strict row compare                 |
| stderr when both ok    | **Yes**         | `stderr_mismatch` (warnings, notices)      |
| Shell dot-commands     | Separate track  | CLI compat, not SQL engine                 |
| Turso-only functions   | Classify        | Flag in triage; not blind sqlite regressions |
| Known COMPAT.md gaps   | Classify        | `known_gap` / `known_partial`; still recorded |
| Nondeterministic fns   | TBD             | `random()`, `datetime('now')` — skip or list when seen |

**Diff kinds:** `outcome_mismatch`, `error_message_mismatch`, `result_mismatch`,
`stderr_mismatch` (future: `parse_error`, `exec_error`, `timeout`, `panic`)

**De-prioritizing (after discovery):** add case ids or patterns to
`inventory/skip_list.yaml`, or rely on COMPAT.md triage classes — do not weaken
the core comparator preemptively.

Reference: Turso's `scripts/diff.sh` compares stdout only and treats errors as
always-fail — this tool diffs more dimensions and records all of them.

---

## Architecture

```
turso_compat_issue_finder/
  PLAN.md
  pyproject.toml
  inventory/
    fetch_metadata.py     # PRAGMA function_list / pragma_list diff
    functions.py          # function SQL generation from metadata
    run_checks.py         # orchestrates all cases + writes reports
    triage.py             # classify mismatches by area / COMPAT.md / noise
    retriage.py           # re-triage from existing behavior_diff.json
    compat_md.py          # parse Turso COMPAT.md status tables
    github_issues.py      # cross-ref open tursodatabase/turso issues
    skip_list.yaml        # curated noise cases to de-prioritize
  run/
    cases.py              # CheckCase / CheckResult dataclasses
    config.py             # engine paths via env vars
    exec.py               # subprocess sqlite3 + tursodb
    compare.py            # outcome + result comparison
    reporting.py          # markdown summary writer
    store.py              # manifest load + results.jsonl persistence (resume)
    smoke.py              # SELECT 1 smoke test
  generate/
    expand.py             # YAML templates × slot fillers → CheckCase list
    archive_util.py       # download / extract / SHA256 for corpus fixtures
    sqltest.py            # extract test blocks from Turso .sqltest files
    sqllogictest.py       # extract queries from sqllogictest .test files
    spider.py             # Spider text-to-SQL manifest
    bird.py               # BIRD dev manifest
    schemapile.py         # SchemaPile DDL manifest
    compat_gaps.py        # COMPAT.md gap cases
    reproducers.py        # load corpus/reproducers.yaml
    corpus.py             # combine all corpus sources (env-driven)
    extract_corpus.py     # CLI: stats, download/ingest, parse, import-issue
  corpus/
    reproducers.yaml      # hand-pasted / imported issue reproducers
    compat_gaps.yaml      # hand-written SQL for COMPAT.md gap rows
    manifest/             # JSONL inventories: spider, bird, schemapile, compat, slt
    fixtures/
      slt/                # local sqllogictest samples (default SLT root)
      spider/             # downloaded Spider data (gitignored)
      bird/               # downloaded BIRD dev bundle (gitignored)
      schemapile/         # downloaded SchemaPile SQL files (gitignored)
  state/
    results.jsonl         # append-only test checklist (resumable runs)
  templates/
    schemas.yaml          # schema presets (empty, one_table, two_table)
    select.yaml           # SELECT templates
    dml.yaml              # INSERT, UPDATE, DELETE
    ddl.yaml              # CREATE TABLE, CREATE INDEX, ALTER
    pragma.yaml           # read-only PRAGMA templates
  report/                 # generated at run time
    metadata_diff.json
    behavior_diff.json
    triage.json
    summary.md
```

**Setup (once):**

```bash
python3 -m venv .venv
.venv/bin/pip install pyyaml
```

**CLI entry points:**

```bash
TURSO_COMPAT_TURSODB=/path/to/tursodb .venv/bin/python -m run.smoke
TURSO_COMPAT_TURSODB=/path/to/tursodb .venv/bin/python -m inventory.fetch_metadata
TURSO_COMPAT_TURSODB=/path/to/tursodb .venv/bin/python -m inventory.run_checks
TURSO_COMPAT_COMPAT_MD=/path/to/turso/COMPAT.md .venv/bin/python -m inventory.retriage
.venv/bin/python -m generate.extract_corpus stats
.venv/bin/python -m generate.extract_corpus parse path/to/file.sqltest
.venv/bin/python -m generate.extract_corpus parse-slt path/to/file.test
.venv/bin/python -m generate.extract_corpus import-issue https://github.com/tursodatabase/turso/issues/1234
```

**Engine invocation:** subprocess CLI (`sqlite3`, `tursodb`) for simplicity and
fidelity to real user behavior. Configurable paths via env or CLI flags.

---

## Reports and triage

After a run, everything you need to inspect individual mismatches lives under
`report/`. Regenerate with the commands above; reports are gitignored (not
committed).

### Output files

| File | Produced by | Purpose |
|------|-------------|---------|
| `report/metadata_diff.json` | `inventory/fetch_metadata.py` | Name-level inventory: which functions/pragmas exist on each engine |
| `report/behavior_diff.json` | `inventory/run_checks.py` | Behavioral comparison: metadata checks + template cases |
| `report/triage.json` | `inventory/triage.py` | Mismatches grouped by area and triage class, with COMPAT.md + GitHub links |
| `report/summary.md` | `inventory/run_checks.py` | Human-readable report; undocumented/actionable cases first |

### `metadata_diff.json` shape

Inventory only — no SQL executed beyond the pragmas themselves.

```json
{
  "functions": {
    "shared": ["abs", "..."],
    "sqlite3_only": ["bm25", "..."],
    "turso_only": ["vector", "..."]
  },
  "pragmas": {
    "shared": ["journal_mode", "..."],
    "sqlite3_only": ["compile_options", "..."],
    "turso_only": ["cipher", "..."]
  }
}
```

Use this to answer “what exists on one engine but not the other?” — not
“do they behave the same?”.

### `behavior_diff.json` shape

One record per test case. Mismatches have a non-null `diff_kind`.

```json
{
  "summary": {
    "total": 145,
    "matched": 129,
    "mismatches": 16,
    "by_diff_kind": {
      "outcome_mismatch": 5,
      "result_mismatch": 11
    }
  },
  "cases": [
    {
      "id": "fn:json_insert",
      "sql": "SELECT json_insert('{}', '$.a');",
      "setup": "",
      "tags": ["function"],
      "diff_kind": "outcome_mismatch",
      "sqlite": { "outcome": "error", "rows": [], "stderr": "..." },
      "turso":   { "outcome": "ok",    "rows": [["{}"]], "stderr": "" }
    },
    {
      "id": "tpl:select_where:0",
      "sql": "SELECT a, b FROM t WHERE a = 1;",
      "setup": "CREATE TABLE t(a INT, b TEXT);\nINSERT INTO t ...",
      "tags": ["select", "dml"],
      "diff_kind": null,
      "sqlite": { "outcome": "ok", "rows": [["1", "one"]], "stderr": "" },
      "turso":   { "outcome": "ok", "rows": [["1", "one"]], "stderr": "" }
    }
  ]
}
```

| Field | Meaning |
|-------|---------|
| `id` | Stable case id — `fn:<name>`, `pragma:<name>`, or `tpl:<template_id>:<variant>` |
| `sql` | Query under test — copy/paste to reproduce |
| `setup` | Schema preset SQL run before `sql` (template cases); empty for fn/pragma cases |
| `tags` | Area tags for filtering (`function`, `pragma`; later `ddl`, `dml`, …) |
| `diff_kind` | `null` = match; `outcome_mismatch` = one ok, one error; `result_mismatch` = both ok, different rows |
| `sqlite` / `turso` | `outcome` (`ok` \| `error`), parsed `rows` (list mode), `stderr` |

### Triage workflow

1. **Run checks**
   ```bash
   TURSO_COMPAT_TURSODB=/path/to/tursodb python3 -m inventory.run_checks
   ```
   Console prints mismatches; full detail is in `report/behavior_diff.json`.

2. **List mismatches only** (JSON or markdown)
   ```bash
   jq '.entries[] | {id, area, triage_class, reason}' report/triage.json
   jq '.by_triage_class.undocumented' report/triage.json
   less report/summary.md
   ```

3. **Filter by area**
   ```bash
   jq '.cases[] | select(.diff_kind != null and (.tags | index("function"))) | .id' report/behavior_diff.json
   ```

4. **Reproduce one case manually** — use `setup` + `sql` from the report:
   ```bash
   SQL="$(jq -r '.cases[] | select(.id=="tpl:select_where:0") | .setup + "\n" + .sql' report/behavior_diff.json)"
   printf '%s\n' "$SQL" | sqlite3 -batch -list :memory:
   printf '%s\n' "$SQL" | /path/to/tursodb -q -m list :memory:
   ```

5. **Trace case back to source**
   | Case prefix | Generated in | Notes |
   |-------------|--------------|-------|
   | `fn:*` | `inventory/functions.py` | SQL from `function_list` metadata (`nargs`, type) |
   | `pragma:*` | `inventory/run_checks.py` | Always `PRAGMA <name>;` (read-only form) |
   | `tpl:*` | `generate/expand.py` | From YAML in `templates/`; variant index = slot combo |
   | `sqltest:*` | `generate/sqltest.py` | Opt-in (`TURSO_COMPAT_SQLTEST=1`); Turso `.sqltest` `test { … }` blocks |
   | `slt:*` | `generate/sqllogictest.py` | From sqllogictest `.test` files; id = `slt:<file>:q<N>`; setup = prior `statement ok` SQL |
   | `spider:*` | `generate/spider.py` | From Spider manifest; file DB per `db_id` |
   | `bird:*` | `generate/bird.py` | From BIRD dev manifest; file DB per `db_id` |
   | `schemapile:*` | `generate/schemapile.py` | Real-world DDL from SchemaPile-Perm |
   | `compat:*` | `generate/compat_gaps.py` | COMPAT.md ❌/🚧 rows + `corpus/compat_gaps.yaml` |
   | `repro:*` | `corpus/reproducers.yaml` | Hand-pasted or `import-issue` from GitHub |

6. **Edit or add templates** — add a YAML file under `templates/` (see existing
   `select.yaml`, `dml.yaml`, etc.). Each template needs `id`, `tags`, `schema`,
   `sql` (with `{slot}` placeholders), and optional `slot_sets`. Schema presets
   live in `templates/schemas.yaml`.

7. **Compare logic** — `run/compare.py`: same parse path for both engines;
   strict diff on outcome, stderr, and ordered result rows.

### Triage classes

| Class | Meaning |
|-------|---------|
| `undocumented` | COMPAT.md says ✅ but behavior differs — highest priority |
| `actionable` | No COMPAT.md entry; worth investigating |
| `known_partial` | COMPAT.md 🚧 Partial |
| `known_gap` | COMPAT.md ❌ No |
| `noise` | Listed in `inventory/skip_list.yaml` (version strings, inventory pragmas, etc.) |

Re-triage without re-running checks: `python3 -m inventory.retriage`

### Expected noise (don't file bugs blindly)

- **`sqlite3_only` functions** — often shell/FTS extensions (`readfile`, `bm25`), not core engine gaps
- **`turso_only` functions** — Turso extensions (vector, uuid, array); not sqlite regressions
- **`fn:sqlite_version`**, **`fn:sqlite_source_id`** — values differ by design
- **`pragma:function_list`**, **`pragma:module_list`** — row counts differ (inventory mismatch, not behavior bug)
- **Auto-generated function SQL** — minimal args may not suit every function; confirm with hand-tuned SQL before filing

### Config env vars

| Variable | Default | Used by |
|----------|---------|---------|
| `TURSO_COMPAT_SQLITE3` | `sqlite3` | all runners |
| `TURSO_COMPAT_TURSODB` | `tursodb` | all runners |
| `TURSO_COMPAT_COMPAT_MD` | _(unset)_ | Path to Turso `COMPAT.md` for gap classification |
| `TURSO_COMPAT_GITHUB_SEARCH` | `1` | Set `0` to skip `gh` issue cross-ref |
| `TURSO_COMPAT_TEMP_DIR` | `/tmp/turso_compat` | Per-case temp file DBs (Spider/BIRD) and scratch space |
| `TURSO_COMPAT_CORPUS` | `1` | Set `0` to skip all corpus loaders (reproducers, slt, spider, bird, schemapile, compat); sqltest is separate |
| `TURSO_COMPAT_SQLTEST` | `0` | Set `1` to include Turso `.sqltest` cases (off by default; redundant with Turso CI) |
| `TURSO_COMPAT_SQLTEST_DIR` | _(auto)_ | Path to Turso `testing/sqltests`; auto-detects `../turso/...` |
| `TURSO_COMPAT_SQLTEST_LIMIT` | _(unset)_ | Cap sqltest cases (useful while iterating) |
| `TURSO_COMPAT_SQLTEST_FILE_DB` | `0` | Set `1` to include non-`:memory:` sqltest files |
| `TURSO_COMPAT_SLT` | `1` | Set `0` to skip sqllogictest `.test` cases |
| `TURSO_COMPAT_SLT_DIR` | _(auto)_ | Path to sqllogictest corpus; auto-detects `../sqllogictest/test`, else `corpus/fixtures/slt/` |
| `TURSO_COMPAT_SLT_LIMIT` | _(unset)_ | Cap sqllogictest query cases |
| `TURSO_COMPAT_SPIDER` | `1` | Set `0` to skip Spider manifest cases |
| `TURSO_COMPAT_SPIDER_DIR` | _(auto)_ | Path to extracted Spider `spider_data/` |
| `TURSO_COMPAT_SPIDER_SPLITS` | `dev,train` | Comma-separated splits to ingest |
| `TURSO_COMPAT_SPIDER_LIMIT` | _(unset)_ | Cap Spider cases at load time |
| `TURSO_COMPAT_SPIDER_MAX_DB_BYTES` | `52428800` | Skip DB files larger than this (50MB) |
| `TURSO_COMPAT_BIRD` | `1` | Set `0` to skip BIRD manifest cases |
| `TURSO_COMPAT_BIRD_DIR` | _(auto)_ | Path to extracted BIRD `dev/` bundle |
| `TURSO_COMPAT_BIRD_LIMIT` | _(unset)_ | Cap BIRD cases at load time |
| `TURSO_COMPAT_BIRD_MAX_DB_BYTES` | `52428800` | Skip BIRD DB files larger than this |
| `TURSO_COMPAT_SCHEMAPILE` | `1` | Set `0` to skip SchemaPile DDL manifest cases |
| `TURSO_COMPAT_SCHEMAPILE_DIR` | _(auto)_ | Path to extracted `sqlfiles_permissive/` |
| `TURSO_COMPAT_SCHEMAPILE_LIMIT` | `5000` | Cap SchemaPile cases at ingest/load |
| `TURSO_COMPAT_SCHEMAPILE_MAX_STMT_BYTES` | `8192` | Skip individual DDL statements larger than this |
| `TURSO_COMPAT_SCHEMAPILE_MAX_FILE_BYTES` | `262144` | Skip source SQL files larger than this (256KB) |
| `TURSO_COMPAT_COMPAT_GAPS` | `1` | Set `0` to skip COMPAT.md gap cases |
| `TURSO_COMPAT_COMPAT_GAPS_LIMIT` | _(unset)_ | Cap compat gap cases |
| `TURSO_COMPAT_RESUME` | `1` | Set `0` to re-run cases already in `state/results.jsonl` |
| `TURSO_COMPAT_SOURCE` | _(unset)_ | Filter run to sources: `spider`, `bird`, `schemapile`, `compat`, `slt`, … |

**Persistent state** (for long corpus runs):

| Path | Purpose |
|------|---------|
| `corpus/manifest/*.jsonl` | Stable inventory: spider (4,483), bird (917), schemapile (5,000), compat (230), slt (sample — expand via `ingest-slt`) |
| `state/results.jsonl` | Append-only checklist: tested / match / mismatch per case id |

**Operational status:** manifests built (~10.6k cases); full corpus run not started. Compare manifest vs ledger with `extract_corpus status`. Resume is on by default (`TURSO_COMPAT_RESUME=1`; `--no-resume` to force re-run).

```bash
.venv/bin/python -m generate.extract_corpus download-spider
.venv/bin/python -m generate.extract_corpus ingest-spider
.venv/bin/python -m generate.extract_corpus download-bird
.venv/bin/python -m generate.extract_corpus ingest-bird
.venv/bin/python -m generate.extract_corpus download-schemapile
.venv/bin/python -m generate.extract_corpus ingest-schemapile
.venv/bin/python -m generate.extract_corpus ingest-compat
.venv/bin/python -m generate.extract_corpus ingest-slt --dir ../sqllogictest/test
.venv/bin/python -m generate.extract_corpus status
TURSO_COMPAT_TURSODB=/path/to/tursodb .venv/bin/python -m inventory.run_checks --source spider
```

---

## Phases

### Phase 0 — Scaffold

- [x] Repo layout, `pyproject.toml` or minimal Python package
- [x] Config: paths to `sqlite3`, `tursodb`, temp dir
- [x] `exec.py`: run multi-statement SQL on `:memory:` or temp file DB
- [x] `compare.py`: strict diff on outcome, stderr, and ordered result rows

### Phase 1 — Metadata diff (quick win)

- [x] `fetch_metadata.py`: run `PRAGMA function_list` / `pragma_list` on both
- [x] Diff report: only-in-sqlite3, only-in-turso, in-both
- [x] For **shared functions**, auto-generate `SELECT fn(minimal_args)` cases
- [x] For **shared pragmas**, try safe read-only forms

### Phase 2 — Template expansion

- [x] YAML template format (skeleton + slots + schema preset + tags)
- [x] Initial set: SELECT, INSERT, UPDATE, CREATE TABLE, CREATE INDEX, PRAGMA
- [x] Slot fillers: literals, simple exprs, function calls from shared list
- [x] JSON report + markdown summary

### Phase 3 — Triage helpers

- [x] Tag failures by area (pragma, ddl, function, dml)
- [x] Optional: cross-ref open GitHub issues by SQL fingerprint / tags
- [x] Optional: skip list from COMPAT.md known gaps (reduce noise)

### Phase 4 — Corpus (optional)

- [x] Turso `.sqltest` parser + `parse` CLI (opt-in for checks via `TURSO_COMPAT_SQLTEST=1`; off by default — redundant with Turso CI)
- [x] Import issue reproducers via `corpus/reproducers.yaml` and `import-issue` CLI
- [x] Parse SQLite sqllogictest `.test` files (`statement ok` setup + `query` cases)
- [x] Text-to-SQL benchmark import (BIRD dev)
- [x] Spider corpus: download + manifest ingest + resumable checks (`--source spider`)
- [x] SchemaPile DDL corpus: download + manifest ingest (`--source schemapile`)
- [x] COMPAT.md ❌ / 🚧 rows as targeted templates (`--source compat`)
- [x] SLT manifest ingest for resumable sqllogictest runs (`ingest-slt`; full corpus not ingested yet — 2 sample cases)

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

- **Language:** Python ✓
- **Template format:** YAML ✓
- **DB mode:** `:memory:` for metadata/templates; file DBs per case for Spider/BIRD ✓; ATTACH/VACUUM-specific cases still TBD
- **Parallelism:** serial first; parallel case runs later
- **Issue linking:** `gh search issues` via `inventory/github_issues.py` ✓ (read-only cross-ref; never auto-file)

---

## First milestone (target: 1–2 sessions)

1. [x] Metadata diff (`function_list`, `pragma_list`)
2. [x] Auto `SELECT func(...)` for every function in the intersection
3. [x] Ten hand-written DDL/DML templates
4. [x] JSON report with `diff_kind` per case

Success = running one command produces a list of reproducible diffs you can
inspect before picking a Turso issue to fix.
