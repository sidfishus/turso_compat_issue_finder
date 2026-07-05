---
name: turso-compat-issue-draft
description: >-
  Find the next Turso/SQLite compatibility mismatch to file, search GitHub for
  duplicates, reproduce with sqlite3 vs tursodb, and write a filing-ready issue
  draft under issues/. Use when triaging turso_compat_issue_finder discrepancies,
  drafting Turso GitHub issues, finding the next compat bug, or re-running the
  issue discovery loop from report/discrepancies.md.
---

# Turso compat issue draft

Workflow for turning a ledger mismatch into a GitHub issue draft. **Never post to GitHub automatically** — drafts only; human files when ready.

**Project root:** `/home/sid/dev/projects/turso_compat_issue_finder`

**Default engines:**

```bash
export TURSO_COMPAT_TURSODB=/home/sid/dev/projects/turso/target/debug/tursodb
export TURSO_COMPAT_COMPAT_MD=/home/sid/dev/projects/turso/COMPAT.md
```

---

## Quick start

From project root:

```bash
# Refresh checklist (optional but recommended)
.venv/bin/python -m inventory.checklist

# Top candidate + repro + GitHub duplicate search
.venv/bin/python -m inventory.next_issue next --repro --search

# List top 10 candidates
.venv/bin/python -m inventory.next_issue candidates
```

Or use the wrapper:

```bash
.cursor/skills/turso-compat-issue-draft/scripts/next-issue.sh
```

---

## Workflow

Copy and track:

```text
- [ ] Refresh checklist
- [ ] Run next_issue (repro + search)
- [ ] Confirm real bug (not noise / known gap / auto-gen artifact)
- [ ] Write draft to issues/<slug>.md
- [ ] Human reviews and files on GitHub
- [ ] Add inventory/known_issues.yaml entry + re-triage
```

### Step 1 — Refresh checklist

```bash
TURSO_COMPAT_COMPAT_MD=/path/to/turso/COMPAT.md .venv/bin/python -m inventory.checklist
```

Read `report/discrepancies.md` if you need the full table.

### Step 2 — Pick candidate

Run `inventory.next_issue next --repro --search`. Ranking (best first):

1. `undocumented` before `actionable` (COMPAT.md ✅ but behavior differs)
2. `outcome_mismatch` before message/row diffs
3. Minimal ids: `fn:*`, `compat:*`, `tpl:*` before `spider:*` corpus hits

Skip without filing:

- `noise`, `known_issue`, `known_gap`, `known_partial`
- Documented unsupported features (`VACUUM`, `WITH RECURSIVE`, window functions)
- Error-message-only diffs when both engines reject (lower priority unless user asks)
- Cases already in `inventory/known_issues.yaml`

If several case ids share one root cause (e.g. four `json_*` fns), **one issue draft** covering all in the reproducer; track case ids in `known_issues.yaml` after filing (not in the GitHub body).

### Step 3 — Reproduce

Always verify manually even if `next_issue --repro` ran:

```bash
SQL='SELECT json_insert('"'{}'"', '"'\$.a'"');'
sqlite3 -batch -list :memory: "$SQL"
"$TURSO_COMPAT_TURSODB" -q -m list :memory: "$SQL"
```

For template/corpus cases with setup SQL, pipe setup + query or use the case's file DB from the ledger row.

### Step 4 — Search GitHub for duplicates

`next_issue --search` runs `gh search issues --repo tursodatabase/turso`. Also check manually:

```bash
gh search issues --repo tursodatabase/turso "json_insert odd" --limit 10 \
  --json number,title,state,url
gh issue view 5545 --repo tursodatabase/turso
```

If duplicate exists: **do not file** — tell the human in chat (issue #, link, why it matches). Add cases to `known_issues.yaml` pointing at the existing issue.

### Step 5 — Write draft

Output path: `issues/<short-slug>.md` (kebab-case, descriptive — not only the case id).

The file is **paste-ready for GitHub** — same shape as [#7757](https://github.com/tursodatabase/turso/issues/7757):

| In `issues/*.md` (public) | In skill / chat only (private) |
|---------------------------|--------------------------------|
| `## Description` | Duplicate search results, “comment on #N instead” |
| `## Reproducer` with `-- Turso:` / `-- SQLite:` | Shell repro commands, COMPAT.md triage class |
| `## SQLite reference` (optional) | Suggested fix area, case ids, yaml snippets |
| Closing line: “Found via [automated…](https://github.com/sidfishus/turso_compat_issue_finder).” | Whether to file vs comment on existing issue |

Use [issue-template.md](issue-template.md). No H1 title in the body — title goes in GitHub’s title field when filing.

Do **not** create GitHub issues, comments, or PRs.

### Step 6 — After human files

Tell the human (or do if asked) — **not** in the issue markdown:

1. Add problem block to `inventory/known_issues.yaml`:

```yaml
<problem_id>:
  issue: <number>
  status: open
  summary: >
    <one-line root cause>
  cases:
    - fn:example
```

2. Re-triage: `.venv/bin/python -m inventory.checklist`
3. Confirm rows show `known_issue` and drop out of actionable count

---

## Related files

| Path | Purpose |
|------|---------|
| `report/discrepancies.md` | Full mismatch checklist |
| `inventory/known_issues.yaml` | Filed issue ↔ case id mapping |
| `inventory/skip_list.yaml` | Noise de-prioritization |
| `issues/*.md` | Filing-ready drafts (committed) |
| `PLAN.md` | Project policy — no auto GitHub posting |

---

## Example invocation

User: “Find the next issue and draft it.”

1. Read this skill
2. Run `.venv/bin/python -m inventory.next_issue next --repro --search`
3. Investigate top candidate; cluster related case ids if same root cause
4. Write `issues/<slug>.md`
5. Tell user: draft path, suggested GitHub title, duplicate status (in chat), and `known_issues.yaml` snippet for after filing
