from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterable, List


def fix(files: Iterable[Path], cfg) -> None:
    """Run latexindent in overwrite mode to fix formatting."""
    _ = cfg
    file_list = [str(f) for f in files]
    if not file_list:
        return

    # -w = overwrite, -s = silent, -c=/tmp = store backups/logs in tmp
    cmd = ["latexindent", "-l=configs/.latexindent.yaml", "-c=/tmp", "-w", "-s"]
    cmd.extend(file_list)

    try:
        subprocess.run(cmd, check=False)
    except FileNotFoundError:
        pass


def run(files: Iterable[Path], cfg) -> List[dict]:
    """Run latexindent in check mode."""
    _ = cfg
    issues = []
    
    # latexindent check mode (-c) usually works per file or writes to log.
    # It exits with non-zero if changes are needed?
    # Actually, -c creates a .diff file or returns exit code. 
    # Reliable way: run on each file, check exit code.
    
    cmd_base = ["latexindent", "-l=configs/.latexindent.yaml", "-c=/tmp", "-k", "-s"]

    for f in files:
        try:
            # check=True would raise, we want return code
            # latexindent -c returns 0 if unchanged, non-zero (usually 1 or 2) if changed/error
            res = subprocess.run(cmd_base + [str(f)], capture_output=True)
            if res.returncode != 0:
                issues.append({
                    "tool": "latexindent",
                    "type": "formatting",
                    "file": str(f),
                    "line": 0,
                    "severity": "warning",
                    "message": "File is not formatted correctly. Run 'make fix' (or 'make review-auto') to correct.",
                })
        except FileNotFoundError:
             return [{"tool": "latexindent", "severity": "error", "message": "latexindent binary not found"}]

    return issues
