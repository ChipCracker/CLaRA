from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple
import re
from pylatexenc.latex2text import LatexNodes2Text


@dataclass
class Segment:
    text: str
    file: str
    start_line: int


def extract_segments(files: Iterable[str], cfg) -> List[Segment]:
    """Extract text segments removing math environments and chunking the result."""
    segments: List[Segment] = []
    for path in files:
        content = Path(path).read_text(encoding="utf-8")
        masked = _mask_preamble_and_comments(content)
        lines = _extract_line_texts(masked)
        if not lines:
            continue
        sentences = _sentences_from_lines(lines)
        if not sentences:
            continue
        for chunk_text, start_line in _chunk_sentences(sentences):
            segments.append(Segment(text=chunk_text, file=str(path), start_line=start_line))
    return segments


def _extract_line_texts(masked: str) -> List[Tuple[str, int]]:
    """Convert each line to plain text and keep line numbers."""
    converter = LatexNodes2Text(math_mode="remove")
    results: List[Tuple[str, int]] = []
    for idx, line in enumerate(masked.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            text = converter.latex_to_text(line)
        except Exception:
            text = line
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            results.append((text, idx))
    return results


def _sentences_from_lines(lines: List[Tuple[str, int]]) -> List[Tuple[str, int]]:
    """Split line texts into sentences while keeping the start line."""
    sentences: List[Tuple[str, int]] = []
    buffer = ""
    start_line = None
    for text, line_no in lines:
        if not text:
            continue
        if not buffer:
            start_line = line_no
            buffer = text
        else:
            buffer = f"{buffer} {text}"

        parts = re.split(r"(?<=[.!?])\s+", buffer)
        if len(parts) == 1:
            continue
        for part in parts[:-1]:
            sentence = part.strip()
            if sentence:
                sentences.append((sentence, start_line or line_no))
            start_line = line_no
        buffer = parts[-1].strip()
        if not buffer:
            start_line = None

    if buffer:
        sentences.append((buffer, start_line or lines[-1][1]))
    return sentences


def _chunk_sentences(
    sentences: List[Tuple[str, int]],
    *,
    target_max_chars: int = 4000,
    overlap_sentences: int = 1,
) -> List[Tuple[str, int]]:
    """
    Combine sentences into larger chunks to keep LLM calls bounded.

    We intentionally approximate "token" limits using character counts to avoid
    adding a tokenizer dependency. This keeps the number of LLM requests low
    (especially important for local CPU inference).
    """
    if not sentences:
        return []

    chunks: List[Tuple[str, int]] = []
    current: List[Tuple[str, int]] = []
    current_len = 0

    def flush() -> None:
        nonlocal current, current_len
        if not current:
            return
        text = " ".join(t for t, _ in current).strip()
        if text:
            chunks.append((text, current[0][1]))
        current = []
        current_len = 0

    for sentence, line_no in sentences:
        s = sentence.strip()
        if not s:
            continue

        add_len = len(s) + (1 if current else 0)
        if current and current_len + add_len > target_max_chars:
            tail = current[-overlap_sentences:] if overlap_sentences > 0 else []
            flush()
            current = tail.copy()
            current_len = sum(len(t) for t, _ in current) + max(0, len(current) - 1)

        if not current:
            current = [(s, line_no)]
            current_len = len(s)
        else:
            current.append((s, line_no))
            current_len += add_len

    flush()
    return chunks


def _mask_preamble_and_comments(content: str) -> str:
    """Mask preamble and comments to avoid LLM feedback on metadata/comments."""
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
    """Replace LaTeX comments with spaces while preserving line structure."""
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


def _mask_macro(text: str, macro: str) -> str:
    if macro not in text:
        return text
    return text.replace(macro, " " * len(macro))
