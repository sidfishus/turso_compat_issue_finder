## Description

Turso rejects `JOIN` queries where an `ON` clause references a table alias that appears later in the `FROM` list. SQLite accepts and executes these queries. COMPAT.md marks `SELECT ... JOIN` as supported.

Reordering the joins so every alias is defined before it is referenced works on both engines.

Found via [automated SQLite/Turso compatibility testing](https://github.com/sidfishus/turso_compat_issue_finder).

## Reproducer

```sql
CREATE TABLE a(x INT);
CREATE TABLE b(y INT);
CREATE TABLE c(z INT);
INSERT INTO a VALUES (1);
INSERT INTO b VALUES (1);
INSERT INTO c VALUES (1);

SELECT * FROM a
JOIN b ON a.x = c.z
JOIN c ON b.y = c.z;
-- Turso:  Parse error: no such table: c
-- SQLite: 1|1|1

SELECT * FROM a
JOIN c ON a.x = c.z
JOIN b ON b.y = c.z;
-- Both: 1|1|1
```