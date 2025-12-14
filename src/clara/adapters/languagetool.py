from __future__ import annotations

import json
import os
import re
import httpx
from pathlib import Path
from typing import Iterable, List

from pylatexenc.latex2text import LatexNodes2Text


def run(files: Iterable[Path], cfg, url_env: str | None = None) -> List[dict]:
    """Run LanguageTool checks via HTTP API."""
    base_url = os.getenv(url_env, "http://localhost:8010") if url_env else "http://localhost:8010"
    if not base_url.endswith("/v2/check"):
        base_url = f"{base_url.rstrip('/')}/v2/check"

    # Load LT config
    lt_cfg_path = Path("configs/languagetool.json")
    disabled_rules = []
    enabled_rules = []
    ignore_words: List[str] = []
    if lt_cfg_path.exists():
        try:
            lt_json = json.loads(lt_cfg_path.read_text(encoding="utf-8"))
            disabled_rules = lt_json.get("disabledRules", [])
            enabled_rules = lt_json.get("enabledRules", [])
            ignore_words = lt_json.get("ignoreWords", [])
        except json.JSONDecodeError:
            pass

    issues = []
    # Convert math to empty text to avoid spelling noise from formulas.
    converter = LatexNodes2Text(math_mode="remove")

    for path in files:
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        # Mask preamble/comments before conversion to reduce noise
        masked = _mask_preamble_and_comments(content)

        # Convert to plain text for LT
        try:
            plain_text = converter.latex_to_text(masked)
        except Exception:
            # Fallback to raw if conversion fails
            plain_text = masked

        if not plain_text.strip():
            continue

        if ignore_words:
            plain_text = _mask_ignore_words(plain_text, ignore_words)
        plain_text = _cleanup_plain_text(plain_text)

        params = {
            "text": plain_text,
            "language": cfg.languages.primary,
            "disabledRules": ",".join(disabled_rules),
            "enabledRules": ",".join(enabled_rules),
        }

        try:
            resp = httpx.post(base_url, data=params, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
        except httpx.RequestError:
            # If server is unreachable, we treat it as a note or skipped
            # For MVP, let's just log a single error issue
            return [{"tool": "languagetool", "severity": "error", "message": "Could not connect to LanguageTool server"}]
        except Exception as e:
            return [{"tool": "languagetool", "severity": "error", "message": str(e)}]

        for match in data.get("matches", []):
            # context text is what LT saw. We try to find it in original content.
            # This is heuristic and imperfect.
            context_str = match.get("context", {}).get("text", "")
            offset = match.get("offset", 0)
            length = match.get("length", 0)
            rule_id = match.get("rule", {}).get("id")
            msg = match.get("message")
            
            # Simple heuristic: map back using context
            # We look for the exact snippet in the original file
            # If plain_text was very different, this might fail.
            # Fallback: line 1
            line = 1
            col = 1
            
            # Extract the error segment from plain_text
            error_segment = plain_text[offset : offset + length]
            
            # Try to find this segment in original content
            # We iterate lines to find "close enough" match?
            # Or just use grep-like find.
            found_idx = masked.find(error_segment)
            if found_idx != -1:
                # Calculate line/col
                preceding = masked[:found_idx]
                line = preceding.count("\n") + 1
                col = len(preceding.split("\n")[-1]) + 1
            
            issues.append({
                "tool": "languagetool",
                "type": "grammar",
                "code": rule_id,
                "file": str(path),
                "line": line,
                "col": col,
                "severity": "warning",  # LT matches are usually warnings
                "message": msg,
                "suggestion": "; ".join(r["value"] for r in match.get("replacements", [])[:3]),
            })

    return issues


def _mask_preamble_and_comments(content: str) -> str:
    masked = _mask_comments(content)

    start = masked.find(r"\begin{document}")
    if start != -1:
        preamble = masked[:start]
        masked = _mask_non_newline(preamble) + masked[start:]

    masked = _mask_macro(masked, r"\maketitle")

    end = masked.find(r"\end{document}")
    if end != -1:
        tail = masked[end + len(r"\end{document}"):]
        masked = masked[:end + len(r"\end{document}")] + _mask_non_newline(tail)

    return masked


def _mask_comments(text: str) -> str:
    out_lines = []
    for line in text.splitlines(keepends=True):
        idx = _find_unescaped_percent(line)
        if idx == -1:
            out_lines.append(line)
            continue
        newline = "\n" if line.endswith("\n") else ""
        visible = line[:idx]
        masked = visible + (" " * (len(line) - idx - len(newline))) + newline
        out_lines.append(masked)
    return "".join(out_lines)


def _find_unescaped_percent(line: str) -> int:
    i = 0
    while True:
        idx = line.find("%", i)
        if idx == -1:
            return -1
        if idx > 0 and line[idx - 1] == "\\":
            i = idx + 1
            continue
        return idx


def _mask_non_newline(text: str) -> str:
    return re.sub(r"[^\n]", " ", text)


def _mask_ignore_words(text: str, words: List[str], replacement: str = "Begriff") -> str:
    masked = text
    for word in words:
        if not word:
            continue
        masked = re.sub(re.escape(word), replacement, masked)
    masked = re.sub(r"[ \t]{2,}", " ", masked)
    return masked


def _cleanup_plain_text(text: str) -> str:
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    lines = text.splitlines()
    cleaned: List[str] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.fullmatch(r"[a-zäöüß]{1,6}", stripped):
            prev_blank = i == 0 or not lines[i - 1].strip()
            next_blank = i == len(lines) - 1 or not lines[i + 1].strip()
            if prev_blank and next_blank:
                continue
        cleaned.append(line)
    return "\n".join(cleaned)


def _mask_macro(text: str, macro: str) -> str:
    if macro not in text:
        return text
    return text.replace(macro, " " * len(macro))
