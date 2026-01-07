"""Incremental review cache for tracking line-level changes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .extract import Segment

CACHE_VERSION = "1.1"
DEFAULT_CACHE_PATH = Path("out/.review_cache.json")


@dataclass
class CachedIssue:
    """Issue stored in cache, without file/line (those are the keys)."""

    tool: str
    type: str
    col: int
    severity: str
    message: str
    code: Optional[str] = None
    suggestion: Optional[str] = None
    adjudication: Optional[Dict[str, Any]] = None

    def to_full_issue(self, file: str, line: int) -> Dict[str, Any]:
        """Reconstruct full issue dict for merging with fresh issues."""
        issue: Dict[str, Any] = {
            "tool": self.tool,
            "type": self.type,
            "file": file,
            "line": line,
            "col": self.col,
            "severity": self.severity,
            "message": self.message,
        }
        if self.code:
            issue["code"] = self.code
        if self.suggestion:
            issue["suggestion"] = self.suggestion
        if self.adjudication:
            issue["adjudication"] = self.adjudication
        return issue

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for JSON storage."""
        d: Dict[str, Any] = {
            "tool": self.tool,
            "type": self.type,
            "col": self.col,
            "severity": self.severity,
            "message": self.message,
        }
        if self.code:
            d["code"] = self.code
        if self.suggestion:
            d["suggestion"] = self.suggestion
        if self.adjudication:
            d["adjudication"] = self.adjudication
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CachedIssue":
        """Deserialize from dict."""
        return cls(
            tool=d["tool"],
            type=d["type"],
            col=d.get("col", 0),
            severity=d["severity"],
            message=d["message"],
            code=d.get("code"),
            suggestion=d.get("suggestion"),
            adjudication=d.get("adjudication"),
        )


@dataclass
class CachedLine:
    """State of a single line in the cache."""

    content_hash: str
    issues: List[CachedIssue] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return {
            "content_hash": self.content_hash,
            "issues": [i.to_dict() for i in self.issues],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CachedLine":
        """Deserialize from dict."""
        return cls(
            content_hash=d["content_hash"],
            issues=[CachedIssue.from_dict(i) for i in d.get("issues", [])],
        )


@dataclass
class CachedSegment:
    """State of an LLM-reviewed segment in the cache."""

    segment_hash: str  # sha256(segment.text)[:16]
    start_line: int
    issues: List[CachedIssue] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return {
            "segment_hash": self.segment_hash,
            "start_line": self.start_line,
            "issues": [i.to_dict() for i in self.issues],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CachedSegment":
        """Deserialize from dict."""
        return cls(
            segment_hash=d["segment_hash"],
            start_line=d["start_line"],
            issues=[CachedIssue.from_dict(i) for i in d.get("issues", [])],
        )


@dataclass
class CachedFile:
    """State of a file in the cache."""

    file_hash: str
    line_count: int
    lines: Dict[int, CachedLine] = field(default_factory=dict)
    segments: Dict[str, CachedSegment] = field(default_factory=dict)  # segment_hash → CachedSegment

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return {
            "file_hash": self.file_hash,
            "line_count": self.line_count,
            "lines": {str(k): v.to_dict() for k, v in self.lines.items()},
            "segments": {k: v.to_dict() for k, v in self.segments.items()},
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CachedFile":
        """Deserialize from dict."""
        return cls(
            file_hash=d["file_hash"],
            line_count=d["line_count"],
            lines={int(k): CachedLine.from_dict(v) for k, v in d.get("lines", {}).items()},
            segments={k: CachedSegment.from_dict(v) for k, v in d.get("segments", {}).items()},
        )


@dataclass
class ReviewCache:
    """Top-level cache structure."""

    version: str = CACHE_VERSION
    timestamp: str = ""
    files: Dict[str, CachedFile] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return {
            "version": self.version,
            "timestamp": self.timestamp,
            "files": {k: v.to_dict() for k, v in self.files.items()},
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ReviewCache":
        """Deserialize from dict."""
        return cls(
            version=d.get("version", CACHE_VERSION),
            timestamp=d.get("timestamp", ""),
            files={k: CachedFile.from_dict(v) for k, v in d.get("files", {}).items()},
        )


@dataclass
class LineChange:
    """Represents change status of a line."""

    current_line: int  # Line number in current file (1-based)
    cached_line: Optional[int]  # Line number in cached state (None if new)
    status: str  # "unchanged", "modified", "new"
    content_hash: str


def compute_line_hash(line: str) -> str:
    """Compute hash of a line, normalizing whitespace."""
    normalized = line.strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def compute_file_hash(content: str) -> str:
    """Compute hash of entire file content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:32]


def compute_segment_hash(segment_text: str) -> str:
    """Compute hash of a segment's text content."""
    return hashlib.sha256(segment_text.encode("utf-8")).hexdigest()[:16]


def load_cache(path: Path = DEFAULT_CACHE_PATH) -> Optional[ReviewCache]:
    """Load cache from disk, return None if not exists or invalid."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != CACHE_VERSION:
            return None  # Version mismatch, invalidate
        return ReviewCache.from_dict(data)
    except (json.JSONDecodeError, KeyError):
        return None


def save_cache(cache: ReviewCache, path: Path = DEFAULT_CACHE_PATH) -> None:
    """Save cache to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cache.timestamp = datetime.utcnow().isoformat() + "Z"
    data = cache.to_dict()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def detect_changes(
    current_lines: List[str], cached_file: Optional[CachedFile]
) -> Tuple[List[LineChange], Set[int]]:
    """
    Detect which lines changed and map cached line numbers to current ones.

    Returns:
        - List of LineChange for each current line
        - Set of cached line numbers that were deleted
    """
    if cached_file is None:
        # All lines are new
        return [
            LineChange(
                current_line=i + 1,
                cached_line=None,
                status="new",
                content_hash=compute_line_hash(line),
            )
            for i, line in enumerate(current_lines)
        ], set()

    # Build hash -> cached line numbers mapping
    cached_hash_to_lines: Dict[str, List[int]] = {}
    for line_no, cached_line in cached_file.lines.items():
        cached_hash_to_lines.setdefault(cached_line.content_hash, []).append(line_no)

    changes: List[LineChange] = []
    used_cached_lines: Set[int] = set()

    for i, line in enumerate(current_lines):
        current_no = i + 1
        content_hash = compute_line_hash(line)

        # Try to find matching cached line
        candidates = cached_hash_to_lines.get(content_hash, [])
        matched_cached = None

        for cached_no in candidates:
            if cached_no not in used_cached_lines:
                matched_cached = cached_no
                used_cached_lines.add(cached_no)
                break

        if matched_cached is not None:
            status = "unchanged"
        else:
            status = "new"

        changes.append(
            LineChange(
                current_line=current_no,
                cached_line=matched_cached,
                status=status,
                content_hash=content_hash,
            )
        )

    # Find deleted lines
    all_cached = set(cached_file.lines.keys())
    deleted = all_cached - used_cached_lines

    return changes, deleted


def analyze_file_changes(
    file_path: Path, cache: Optional[ReviewCache]
) -> Tuple[List[LineChange], Optional[CachedFile], bool]:
    """
    Analyze a file for changes.

    Returns:
        - List of LineChange objects
        - CachedFile if it existed
        - bool: True if file needs any checking at all
    """
    content = file_path.read_text(encoding="utf-8")
    current_hash = compute_file_hash(content)
    lines = content.splitlines()

    cached_file = None
    file_key = str(file_path)
    if cache and file_key in cache.files:
        cached_file = cache.files[file_key]
        # Quick check: if file hash unchanged, no work needed
        if cached_file.file_hash == current_hash:
            return [], cached_file, False

    changes, _deleted = detect_changes(lines, cached_file)
    needs_check = any(c.status == "new" for c in changes)

    return changes, cached_file, needs_check


def get_cached_issues_for_unchanged(
    file_path: str, changes: List[LineChange], cached_file: CachedFile
) -> List[Dict[str, Any]]:
    """Get issues from cache for unchanged lines, with updated line numbers."""
    issues: List[Dict[str, Any]] = []
    for change in changes:
        if change.status == "unchanged" and change.cached_line:
            cached_line = cached_file.lines.get(change.cached_line)
            if cached_line:
                for cached_issue in cached_line.issues:
                    issues.append(cached_issue.to_full_issue(file_path, change.current_line))
    return issues


def get_lines_needing_check(changes: List[LineChange]) -> Set[int]:
    """Get line numbers that need fresh checking."""
    return {change.current_line for change in changes if change.status == "new"}


def get_cached_llm_issues(
    segments: List["Segment"],
    cached_file: Optional[CachedFile],
) -> Tuple[List["Segment"], List[Dict[str, Any]]]:
    """
    Filter segments and return cached LLM issues for unchanged segments.

    Returns:
        - List of segments that need fresh LLM review (new or changed)
        - List of cached issues for unchanged segments (with updated line numbers)
    """
    if cached_file is None:
        return segments, []

    fresh_segments: List["Segment"] = []
    cached_issues: List[Dict[str, Any]] = []

    for segment in segments:
        seg_hash = compute_segment_hash(segment.text)

        if seg_hash in cached_file.segments:
            cached_seg = cached_file.segments[seg_hash]
            for cached_issue in cached_seg.issues:
                cached_issues.append(
                    cached_issue.to_full_issue(segment.file, segment.start_line)
                )
        else:
            fresh_segments.append(segment)

    return fresh_segments, cached_issues


def issue_to_cached(issue: Dict[str, Any]) -> CachedIssue:
    """Convert a full issue dict to CachedIssue."""
    return CachedIssue(
        tool=issue.get("tool", "unknown"),
        type=issue.get("type", "generic"),
        col=issue.get("col", 0),
        severity=issue.get("severity", "note"),
        message=issue.get("message", ""),
        code=issue.get("code"),
        suggestion=issue.get("suggestion"),
        adjudication=issue.get("adjudication"),
    )


def build_cache_from_results(
    files: List[Path],
    issues: List[Dict[str, Any]],
    segments: Optional[List["Segment"]] = None,
) -> ReviewCache:
    """Build new cache from review results."""
    cache = ReviewCache()

    # Separate LLM issues from line-based issues
    llm_issues: List[Dict[str, Any]] = []
    line_issues_list: List[Dict[str, Any]] = []
    for issue in issues:
        if issue.get("tool") == "llm":
            llm_issues.append(issue)
        else:
            line_issues_list.append(issue)

    # Index line-based issues by (file, line)
    issue_index: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
    for issue in line_issues_list:
        key = (issue.get("file", ""), issue.get("line", 0))
        issue_index.setdefault(key, []).append(issue)

    # Index LLM issues by (file, start_line) for segment matching
    llm_issue_index: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
    for issue in llm_issues:
        key = (issue.get("file", ""), issue.get("line", 0))
        llm_issue_index.setdefault(key, []).append(issue)

    # Build segment index: segment_hash → (segment, issues)
    segment_cache: Dict[str, Dict[str, CachedSegment]] = {}  # file → {hash → CachedSegment}
    if segments:
        for segment in segments:
            seg_hash = compute_segment_hash(segment.text)
            seg_issues = llm_issue_index.get((segment.file, segment.start_line), [])
            cached_segment = CachedSegment(
                segment_hash=seg_hash,
                start_line=segment.start_line,
                issues=[issue_to_cached(iss) for iss in seg_issues],
            )
            segment_cache.setdefault(segment.file, {})[seg_hash] = cached_segment

    for file_path in files:
        content = file_path.read_text(encoding="utf-8")
        lines = content.splitlines()
        file_key = str(file_path)

        cached_file = CachedFile(
            file_hash=compute_file_hash(content),
            line_count=len(lines),
            lines={},
            segments=segment_cache.get(file_key, {}),
        )

        for i, line in enumerate(lines):
            line_no = i + 1
            line_iss = issue_index.get((file_key, line_no), [])

            cached_line = CachedLine(
                content_hash=compute_line_hash(line),
                issues=[issue_to_cached(iss) for iss in line_iss],
            )
            cached_file.lines[line_no] = cached_line

        cache.files[file_key] = cached_file

    return cache
