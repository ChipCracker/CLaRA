from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


DIRECTIVE_RE = re.compile(
    r"\bclara:\s*(ignore-next-line|ignore-start|ignore-end|ignore-file)\b",
    re.IGNORECASE,
)


@dataclass
class SuppressionRange:
    start: int
    end: int
    rule: str


@dataclass
class FileSuppressions:
    ignore_file: bool
    ranges: List[SuppressionRange]


def apply_suppressions(issues: List[dict]) -> List[dict]:
    """Mark suppressed issues and return the active (non-suppressed) list."""
    file_paths = {
        _normalize_path(issue.get("file"))
        for issue in issues
        if issue.get("file")
    }
    suppressions = _collect_suppressions(file_paths)
    active: List[dict] = []
    for issue in issues:
        suppression = _match_suppression(issue, suppressions)
        if suppression:
            issue["suppressed"] = True
            issue["suppression"] = suppression
            continue
        active.append(issue)
    return active


def _collect_suppressions(paths: Iterable[Path]) -> Dict[Path, FileSuppressions]:
    data: Dict[Path, FileSuppressions] = {}
    for path in paths:
        if not path:
            continue
        if path in data:
            continue
        data[path] = _scan_file(path)
    return data


def _scan_file(path: Path) -> FileSuppressions:
    if not path.exists():
        return FileSuppressions(ignore_file=False, ranges=[])
    lines = path.read_text(encoding="utf-8").splitlines()
    ranges: List[SuppressionRange] = []
    ignore_file = False
    active_start: Optional[int] = None
    for idx, line in enumerate(lines, start=1):
        directive = _parse_directive(line)
        if not directive:
            continue
        if directive == "ignore-file":
            ignore_file = True
            continue
        if directive == "ignore-next-line":
            ranges.append(SuppressionRange(idx + 1, idx + 1, "ignore-next-line"))
            continue
        if directive == "ignore-start":
            if active_start is None:
                active_start = idx
            continue
        if directive == "ignore-end":
            if active_start is not None:
                ranges.append(SuppressionRange(active_start, idx, "ignore-block"))
                active_start = None
            continue
    if active_start is not None:
        ranges.append(SuppressionRange(active_start, len(lines), "ignore-block"))
    return FileSuppressions(ignore_file=ignore_file, ranges=ranges)


def _parse_directive(line: str) -> Optional[str]:
    comment = _comment_text(line)
    if not comment:
        return None
    match = DIRECTIVE_RE.search(comment)
    if not match:
        return None
    return match.group(1).lower()


def _comment_text(line: str) -> Optional[str]:
    for idx, ch in enumerate(line):
        if ch == "%" and (idx == 0 or line[idx - 1] != "\\"):
            return line[idx + 1 :]
    return None


def _match_suppression(issue: dict, suppressions: Dict[Path, FileSuppressions]) -> Optional[dict]:
    file_path = _normalize_path(issue.get("file"))
    if not file_path:
        return None
    info = suppressions.get(file_path)
    if not info:
        return None
    if info.ignore_file:
        return {"rule": "ignore-file"}
    line = int(issue.get("line") or 0)
    if line <= 0:
        return None
    for rng in info.ranges:
        if rng.start <= line <= rng.end:
            return {"rule": rng.rule}
    return None


def _normalize_path(value: str | Path | None) -> Optional[Path]:
    if not value:
        return None
    try:
        return Path(value).resolve()
    except OSError:
        return Path(value)
