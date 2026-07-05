from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

KNOWN_ISSUES_PATH = Path(__file__).resolve().parent / "known_issues.yaml"
ISSUE_URL_TEMPLATE = "https://github.com/tursodatabase/turso/issues/{issue}"


@dataclass(frozen=True)
class KnownProblem:
    id: str
    issue: int
    status: str
    summary: str
    cases: frozenset[str]

    @property
    def url(self) -> str:
        return ISSUE_URL_TEMPLATE.format(issue=self.issue)


@dataclass(frozen=True)
class CaseIssueLink:
    problem_id: str
    issue: int
    issue_url: str
    issue_status: str
    summary: str


def load_known_issues(path: Path = KNOWN_ISSUES_PATH) -> tuple[dict[str, KnownProblem], dict[str, CaseIssueLink]]:
    if not path.exists():
        return {}, {}

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    problems_raw = data.get("problems") or {}

    problems: dict[str, KnownProblem] = {}
    case_links: dict[str, CaseIssueLink] = {}

    for problem_id, payload in problems_raw.items():
        if not isinstance(payload, dict):
            continue
        issue = payload.get("issue")
        if issue is None:
            continue
        problem = KnownProblem(
            id=problem_id,
            issue=int(issue),
            status=str(payload.get("status") or "open"),
            summary=str(payload.get("summary") or "").strip(),
            cases=frozenset(payload.get("cases") or []),
        )
        problems[problem_id] = problem
        link = CaseIssueLink(
            problem_id=problem_id,
            issue=problem.issue,
            issue_url=problem.url,
            issue_status=problem.status,
            summary=problem.summary,
        )
        for case_id in problem.cases:
            case_links[case_id] = link

    return problems, case_links
