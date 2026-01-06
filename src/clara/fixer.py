from __future__ import annotations

import json
import re
import difflib
from pathlib import Path
from typing import List, Dict, Any, Iterable

from .config import ClaraConfig
from .prompts import load_prompt

ANNOTATION_PREFIX = "CLaRA-LLM"
MAX_ANNOTATION_LEN = 160
INCLUDE_RATIONALE = False
FIX_PREFIX = "CLaRA-FIX"
FIX_INLINE_RE = re.compile(rf"\s*%\s*{re.escape(FIX_PREFIX)}:.*$")
ANNOTATION_RE = re.compile(rf"^\s*%+\s*{re.escape(ANNOTATION_PREFIX)}:")


def load_issues(issues_path: str) -> List[Dict[str, Any]]:
    path = Path(issues_path)
    if not path.exists():
        print(f"No issues file found at {issues_path}. Run 'make check' first.")
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("issues", [])
    except json.JSONDecodeError:
        print("Invalid JSON in issues file.")
        return []


def apply_fixes(issues_path: str, cfg: ClaraConfig) -> None:
    """
    Reads issues from JSON and uses LLM to fix non-LLM issues.
    Applies changes to files in-place (carefully).
    """
    issues = load_issues(issues_path)
    if not issues:
        return
    apply_fixes_from_issues(issues, cfg)


def apply_fixes_from_issues(issues: Iterable[Dict[str, Any]], cfg: ClaraConfig) -> None:
    """Apply fixes from an in-memory issues list."""
    fixable_issues = [
        i for i in issues
        if not i.get("suppressed")
        and i.get("tool") in ("languagetool", "codespell")
        and i.get("file")
        and i.get("line")
    ]

    if not fixable_issues:
        print("No fixable content issues found.")
        return

    files_map: Dict[str, List[Dict[str, Any]]] = {}
    for issue in fixable_issues:
        fname = issue["file"]
        files_map.setdefault(fname, []).append(issue)

    for fname, file_issues in files_map.items():
        _process_file(fname, file_issues, cfg)


def annotate_llm_comments(
    issues: Iterable[Dict[str, Any]],
    cfg: ClaraConfig,
    files: Iterable[str] | None = None,
) -> None:
    """Insert LLM suggestions as LaTeX comments next to affected lines."""
    _ = cfg
    if files is None:
        files = {i.get("file") for i in issues if i.get("file")}
    for fname in files:
        _remove_existing_comments(fname)

    llm_issues = [
        i for i in issues
        if not i.get("suppressed")
        and i.get("tool") == "llm"
        and i.get("file")
        and i.get("line")
    ]
    if not llm_issues:
        print("No LLM annotations to add.")
        return

    files_map: Dict[str, List[Dict[str, Any]]] = {}
    for issue in llm_issues:
        files_map.setdefault(issue["file"], []).append(issue)

    for fname, file_issues in files_map.items():
        _annotate_file(fname, file_issues)


def apply_adjudicated_fixes(issues: Iterable[Dict[str, Any]]) -> None:
    """Apply LLM-adjudicated fixes and append inline comments."""
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for issue in issues:
        if issue.get("suppressed"):
            continue
        adj = issue.get("adjudication") or {}
        if not adj.get("accept"):
            continue
        fix = adj.get("fix")
        if not fix or not issue.get("file") or not issue.get("line"):
            continue
        issue["fix"] = fix
        issue["comment"] = adj.get("comment", "")
        grouped.setdefault(issue["file"], []).append(issue)

    for fname, file_issues in grouped.items():
        _apply_inline_fixes(fname, file_issues)


def _process_file(fname: str, issues: List[Dict], cfg: ClaraConfig):
    fpath = Path(fname)
    if not fpath.exists():
        return

    lines = fpath.read_text(encoding="utf-8").splitlines()
    
    # We need to process from bottom to top to keep line numbers valid?
    # Actually, replacing a line with a fixed line might not change line count if it's 1:1.
    # But LLM might merge/split lines. 
    # Safest strategy: 
    # 1. Identify "bad lines".
    # 2. Group issues by line index.
    # 3. Fix line by line (or small blocks). 
    
    # Sort issues by line index descending
    issues.sort(key=lambda x: x.get("line", 0), reverse=True)
    
    # Group by line
    lines_issues: Dict[int, List[Dict]] = {}
    for i in issues:
        ln = int(i.get("line", 0)) - 1  # 0-indexed
        if ln < 0 or ln >= len(lines):
            continue
        if ln not in lines_issues:
            lines_issues[ln] = []
        lines_issues[ln].append(i)

    # Load prompt
    system_prompt = load_prompt("prompt_fix", cfg, default="Fix the error.")

    # Iterate over affected lines (descending order)
    for line_idx in sorted(lines_issues.keys(), reverse=True):
        original_text = lines[line_idx]
        current_issues = lines_issues[line_idx]
        
        # Construct error description
        error_descs = []
        for issue in current_issues:
            msg = f"- [{issue['tool']}] {issue['message']}"
            if issue.get("suggestion"):
                msg += f" (Suggestion: {issue['suggestion']})"
            error_descs.append(msg)
        
        error_block = "\n".join(error_descs)
        
        user_msg = f"Original Text:\n{original_text}\n\nErrors:\n{error_block}\n\nCorrected Text:"
        
        # Call LLM
        # We need a simple "generate text" call, reusing adapters is tricky as they expect segments.
        # We'll make a direct helper call here or extend adapters.
        # Let's use a helper that dispatches based on config.
        
        print(f"Fixing {fname}:{line_idx+1}...")
        try:
            fixed_text = _call_llm_for_fix(cfg, system_prompt, user_msg)
            
            # Clean response: strip CoT <think> blocks and extra text
            if "</think>" in fixed_text:
                fixed_text = fixed_text.split("</think>")[-1]
            
            # Sanity check: if empty, don't replace
            fixed_text = fixed_text.strip()
            if "\n" in fixed_text:
                print("  Skipped (multi-line response)")
            elif fixed_text:
                if _is_safe_fix(original_text, fixed_text):
                    lines[line_idx] = fixed_text.strip()
                else:
                    print("  Skipped (unsafe fix)")
            else:
                print(f"  Skipped (empty response)")
                
        except Exception as e:
            print(f"  Failed to fix: {e}")

    # Write back
    fpath.write_text("\n".join(lines), encoding="utf-8")
    print(f"Applied fixes to {fname}")


def _remove_existing_comments(fname: str) -> None:
    fpath = Path(fname)
    if not fpath.exists():
        return
    lines = fpath.read_text(encoding="utf-8").splitlines()
    base_lines = [line for line in lines if not ANNOTATION_RE.match(line)]
    if base_lines != lines:
        fpath.write_text("\n".join(base_lines), encoding="utf-8")


def _annotate_file(fname: str, issues: List[Dict[str, Any]]) -> None:
    fpath = Path(fname)
    if not fpath.exists():
        return

    lines = fpath.read_text(encoding="utf-8").splitlines()
    if not lines:
        return

    removed_before: List[int] = []
    removed_count = 0
    for line in lines:
        if ANNOTATION_RE.match(line):
            removed_count += 1
        removed_before.append(removed_count)

    base_lines = [line for line in lines if not ANNOTATION_RE.match(line)]

    grouped: Dict[int, List[Dict[str, Any]]] = {}
    for issue in issues:
        try:
            orig_line = int(issue.get("line", 0))
        except (TypeError, ValueError):
            continue
        if orig_line <= 0 or orig_line > len(lines):
            continue
        adjusted = orig_line - removed_before[orig_line - 1]
        if adjusted <= 0 or adjusted > len(base_lines):
            continue
        grouped.setdefault(adjusted, []).append(issue)

    if not grouped:
        return

    for line_no in sorted(grouped.keys(), reverse=True):
        idx = line_no - 1
        issues_for_line = grouped[line_no]
        inline = _build_inline_comment(issues_for_line)
        if not inline:
            continue
        base_lines[idx] = f"{base_lines[idx]} {inline}"

    fpath.write_text("\n".join(base_lines), encoding="utf-8")
    print(f"Added LLM annotations to {fname}")


def _build_comment_lines(issues: List[Dict[str, Any]], indent: str) -> List[str]:
    lines: List[str] = []
    for issue in issues:
        suggestion = _sanitize_comment(issue.get("suggestion", ""))
        message = _sanitize_comment(issue.get("message", ""))
        if not suggestion and not message:
            suggestion = "Suggestion from LLM."
        if INCLUDE_RATIONALE and message:
            text = f"{suggestion} (Warum: {message})" if suggestion else message
        else:
            text = suggestion or message
        text = _truncate_comment(text)
        comment = f"{indent}% {ANNOTATION_PREFIX}: {text}"
        lines.append(comment)
    return lines


def _sanitize_comment(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def _truncate_comment(text: str) -> str:
    if len(text) <= MAX_ANNOTATION_LEN:
        return text
    return text[: MAX_ANNOTATION_LEN - 1].rstrip() + "…"


def _build_inline_comment(issues: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for issue in issues:
        suggestion = _sanitize_comment(issue.get("suggestion", ""))
        message = _sanitize_comment(issue.get("message", ""))
        if not suggestion and not message:
            suggestion = "Suggestion from LLM."
        if INCLUDE_RATIONALE and message:
            text = f"{suggestion} (Warum: {message})" if suggestion else message
        else:
            text = suggestion or message
        text = _truncate_comment(text)
        if text:
            parts.append(text)
    if not parts:
        return ""
    return f"% {ANNOTATION_PREFIX}: " + " | ".join(parts)


def _apply_inline_fixes(fname: str, issues: List[Dict[str, Any]]) -> None:
    fpath = Path(fname)
    if not fpath.exists():
        return
    lines = fpath.read_text(encoding="utf-8").splitlines()
    if not lines:
        return
    lines = [_strip_fix_inline(line) for line in lines]

    by_line: Dict[int, List[Dict[str, Any]]] = {}
    for issue in issues:
        try:
            line_no = int(issue.get("line", 0))
        except (TypeError, ValueError):
            continue
        if line_no <= 0 or line_no > len(lines):
            continue
        by_line.setdefault(line_no, []).append(issue)

    for line_no in sorted(by_line.keys(), reverse=True):
        idx = line_no - 1
        original = lines[idx]
        # Apply the first fix per line for now.
        fix = by_line[line_no][0].get("fix", "").strip()
        if not fix:
            continue
        comment = _build_fix_inline_comment(by_line[line_no][0], original, fix)
        lines[idx] = f"{fix} {comment}".rstrip()
        by_line[line_no][0]["fixed"] = True
        by_line[line_no][0]["severity"] = "note"

    fpath.write_text("\n".join(lines), encoding="utf-8")
    print(f"Applied adjudicated fixes to {fname}")


def _strip_fix_inline(line: str) -> str:
    return re.sub(FIX_INLINE_RE, "", line).rstrip()


def _build_fix_inline_comment(issue: Dict[str, Any], original: str, fixed: str) -> str:
    comment = issue.get("comment", "").strip()
    if not comment:
        comment = "korrigiert"
    comment = _truncate_comment(comment)
    return f"% {FIX_PREFIX}: {comment}"


def _is_safe_fix(original: str, fixed: str) -> bool:
    if not fixed or fixed == original:
        return False
    fixed = fixed.strip()
    original = original.rstrip()
    if not fixed:
        return False
    if original.lstrip().startswith("\\"):
        return False
    if "%" in fixed and "%" not in original:
        return False
    if original.count("{") != fixed.count("{") or original.count("}") != fixed.count("}"):
        return False
    if original.count("$") != fixed.count("$"):
        return False
    if _latex_commands(original) != _latex_commands(fixed):
        return False
    ratio = difflib.SequenceMatcher(a=original, b=fixed).ratio()
    if ratio < 0.85:
        return False
    max_delta = max(10, int(len(original) * 0.15))
    if abs(len(fixed) - len(original)) > max_delta:
        return False
    return True


def _latex_commands(text: str) -> list[str]:
    return re.findall(r"\\[A-Za-z@]+", text)


def _call_llm_for_fix(cfg: ClaraConfig, sys_prompt: str, user_msg: str) -> str:
    # Minimal adapter dispatch
    import httpx
    import os
    
    if cfg.llm.provider in ("openai", "lm-studio"):
        base_url = cfg.llm.api_url or "http://localhost:1234/v1"
        url = f"{base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": cfg.llm.model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_msg}
            ],
            "stream": False
        }
        if cfg.llm.temperature is not None:
            payload["temperature"] = cfg.llm.temperature
            
        headers = {}
        if os.getenv("OPENAI_API_KEY"):
            headers["Authorization"] = f"Bearer {os.getenv('OPENAI_API_KEY')}"
            
        timeout = cfg.llm.timeout_seconds or 60
        resp = httpx.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
        
    elif cfg.llm.provider == "ollama":
        base_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        url = f"{base_url.rstrip('/')}/api/chat"
        payload = {
            "model": cfg.llm.model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_msg}
            ],
            "stream": False,
            "options": {}
        }
        if cfg.llm.temperature is not None:
            payload["options"]["temperature"] = cfg.llm.temperature

        timeout = cfg.llm.timeout_seconds or 60
        resp = httpx.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json()["message"]["content"]
    
    return ""
