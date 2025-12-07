from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Iterable, List


def run(files: Iterable[Path], cfg) -> List[dict]:
    """Run vale on files and parse JSON output."""
    _ = cfg
    issues = []
    file_list = [str(f) for f in files]
    
    if not file_list:
        return []

    # --no-exit ensures vale returns 0 even if errors found (we parse stdout)
    cmd = ["vale", "--no-exit", "--output=JSON", "--config=configs/vale.ini"]
    cmd.extend(file_list)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        return [{"tool": "vale", "severity": "error", "message": "vale binary not found"}]

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        # Fallback if vale fails or outputs non-JSON (e.g. config error)
        if result.stderr:
            return [{"tool": "vale", "severity": "error", "message": f"Vale execution failed: {result.stderr.strip()}"}]
        return []

    for filename, checks in data.items():
        for check in checks:
            severity = check.get("Severity", "warning")
            # Map vale severity to ours if needed, though they match mostly
            issues.append({
                "tool": "vale",
                "type": "style",
                "code": check.get("Check"),
                "file": filename,
                "line": check.get("Line"),
                "col": check.get("Span", [0])[0],
                "severity": severity,
                "message": check.get("Message"),
            })

    return issues
