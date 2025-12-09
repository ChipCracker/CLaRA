from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Iterable, List


def run(files: Iterable[Path], cfg) -> List[dict]:
    """Run chktex on files and parse output."""
    _ = cfg  # Config might be used for extra args later
    issues = []
    
    # We use a custom format to make parsing robust:
    # %f = file, %l = line, %c = col, %k = kind, %n = number, %m = message
    cmd = ["chktex", "-q", "-I", "-v0", "-l", "configs/.chktexrc", "-f%f:%l:%c:%k:%n:%m\n"]
    cmd.extend(str(f) for f in files)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        # If chktex is missing (e.g. local run without docker), warn or skip
        return [{"tool": "chktex", "severity": "error", "message": "chktex binary not found"}]

    # Output format: filename:line:col:kind:num:msg
    pattern = re.compile(r"^(.*?):(\d+):(\d+):(Warning|Error):(\d+):(.*)$")

    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        
        match = pattern.match(line)
        if match:
            fpath, l, c, kind, num, msg = match.groups()
            severity = "error" if kind == "Error" else "warning"
            issues.append({
                "tool": "chktex",
                "type": "latex_lint",
                "code": f"chktex:{num}",
                "file": fpath,
                "line": int(l),
                "col": int(c),
                "severity": severity,
                "message": msg.strip(),
            })

    return issues
