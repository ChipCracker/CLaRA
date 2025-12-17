from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Iterable, List


def run(files: Iterable[Path], cfg) -> List[dict]:
    """Run codespell on files."""
    _ = cfg
    issues = []
    file_list = [str(f) for f in files]

    if not file_list:
        return []

    cmd = ["codespell"]
    cmd.extend(file_list)

    try:
        # codespell returns non-zero if typos found
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        return [{"tool": "codespell", "severity": "error", "message": "codespell binary not found"}]

    # Output format: filename:line: typo ==> correction
    # Example: paper.tex:10: teh ==> the
    pattern = re.compile(r"^(.*?):(\d+):\s+(.*)$")

    # Combine stdout and stderr just in case, though usually stdout
    output = result.stdout + result.stderr

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
            
        match = pattern.match(line)
        if match:
            fpath, lineno, msg = match.groups()
            issues.append({
                "tool": "codespell",
                "type": "typo",
                "file": fpath,
                "line": int(lineno),
                "severity": "warning",
                "message": msg,
            })

    return issues
