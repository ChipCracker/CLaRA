from __future__ import annotations

from typing import Dict, Iterable, List


class Issue(Dict):
    """Alias for issue dictionaries."""


SEVERITY_ORDER = {"error": 2, "warning": 1, "note": 0}


def normalize(issue: Issue) -> Issue:
    """Ensure required keys exist and normalize severity/type."""
    normalized = {
        "tool": issue.get("tool", "unknown"),
        "type": issue.get("type", "generic"),
        "file": issue.get("file"),
        "line": issue.get("line", 0),
        "col": issue.get("col", 0),
        "severity": issue.get("severity", "note"),
        "message": issue.get("message", ""),
    }
    if "code" in issue:
        normalized["code"] = issue["code"]
    if "suggestion" in issue:
        normalized["suggestion"] = issue["suggestion"]
    if "adjudication" in issue:
        normalized["adjudication"] = issue["adjudication"]
    if "fix" in issue:
        normalized["fix"] = issue["fix"]
    if "comment" in issue:
        normalized["comment"] = issue["comment"]
    if "fixed" in issue:
        normalized["fixed"] = issue["fixed"]
    return normalized


def summarize(issues: Iterable[Issue]) -> Dict[str, int]:
    """Compute summary counts grouped by severity."""
    summary = {"errors": 0, "warnings": 0, "notes": 0}
    for issue in issues:
        if issue.get("suppressed"):
            continue
        severity = issue.get("severity", "note")
        if severity == "error":
            summary["errors"] += 1
        elif severity == "warning":
            summary["warnings"] += 1
        else:
            summary["notes"] += 1
    return summary
