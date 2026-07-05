from __future__ import annotations

import json
import subprocess


def search_turso_issues(query: str, *, limit: int = 5) -> list[dict[str, str]]:
    try:
        proc = subprocess.run(
            [
                "gh",
                "search",
                "issues",
                "--repo",
                "tursodatabase/turso",
                query,
                "--state",
                "open",
                "--limit",
                str(limit),
                "--json",
                "number,title,url",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []

    if proc.returncode != 0:
        return []

    try:
        issues = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []

    return [
        {
            "number": str(issue["number"]),
            "title": issue["title"],
            "url": issue["url"],
        }
        for issue in issues
    ]


def issues_for_case(case_id: str) -> list[dict[str, str]]:
    from inventory.compat_md import subject_for_case_id

    subject = subject_for_case_id(case_id)
    queries = [subject, f"{subject} compatibility"]
    seen_urls: set[str] = set()
    results: list[dict[str, str]] = []
    for query in queries:
        for issue in search_turso_issues(query):
            if issue["url"] in seen_urls:
                continue
            seen_urls.add(issue["url"])
            results.append(issue)
    return results[:5]
