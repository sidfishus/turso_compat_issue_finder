# GitHub issue body template

Copy the file contents into the GitHub issue body. Match [#7757](https://github.com/tursodatabase/turso/issues/7757): `## Description`, `## Reproducer`; add `## SQLite reference` only when a doc quote clarifies expected behavior.

Do **not** put filing notes, fix hints, shell commands, or `known_issues.yaml` snippets in `issues/*.md` — those stay in the skill / chat.

**Issue title** (GitHub title field, not in the markdown file): short behavior summary, e.g. `json_insert() accepts path-only calls that SQLite rejects`.

---

## Description

<What Turso does vs SQLite. One or two short paragraphs. Optional scope note if related calls already match on both engines.>

Found via [automated SQLite/Turso compatibility testing](https://github.com/sidfishus/turso_compat_issue_finder).

## Reproducer

~~~sql
<minimal SQL>
-- Turso:  <output or error>
-- SQLite: <output or error>

<more variants; optional case that works on both with `-- Both:`>
~~~

## SQLite reference

<Optional section — omit entirely if the reproducer is self-explanatory.>

From [Section title](https://www.sqlite.org/…):

> <Short quote stating the rule SQLite follows.>
