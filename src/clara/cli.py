from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path
from typing import Iterable, List, Sequence

from .config import ClaraConfig, load_config
from .extract import extract_segments
from .report import normalize, summarize
from .suppressions import apply_suppressions
from . import adapters


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="CLaRA CLI (Continuous LaTeX Review Assistant). Standard workflow: review-auto; other commands are for debug/diagnostics.",
        epilog="Tip: use `make review-auto` for normal runs; `check`, `review-fix`, `fix`, `fix-content`, `annotate` are debug helpers.",
    )
    parser.add_argument("cmd", choices=["review-auto", "check", "fix", "fix-content", "annotate", "review-fix"])
    parser.add_argument("--fast", action="store_true")
    parser.add_argument("--with-llm", action="store_true")
    parser.add_argument("--files", nargs="*")
    parser.add_argument("--json", dest="json_out")
    parser.add_argument("--issues", dest="issues_in", help="Input JSON issues for fix-content/annotate")
    args = parser.parse_args()

    cfg = load_config("clara.toml")
    files = resolve_files(args.files, cfg)

    if args.cmd == "fix":
        adapters.latexindent.fix(files, cfg)
        print("formatted")
        return
        
    if args.cmd == "fix-content":
        from .fixer import apply_fixes
        if not args.issues_in:
            print("Error: --issues <path> is required for fix-content")
            sys.exit(1)
        apply_fixes(args.issues_in, cfg)
        print("content fixes applied")
        return
        
    if args.cmd == "annotate":
        from .fixer import annotate_llm_comments, load_issues
        if not args.issues_in:
            print("Error: --issues <path> is required for annotate")
            sys.exit(1)
        issues = load_issues(args.issues_in)
        annotate_llm_comments(issues, cfg)
        print("annotations added")
        return

    # review-auto should behave like `make fix` w.r.t. formatting: format first, then lint.
    if args.cmd in ("review-auto", "review-fix"):
        adapters.latexindent.fix(files, cfg)

    issues = []
    issues += adapters.latexindent.run(files, cfg)
    issues += adapters.chktex.run(files, cfg)
    issues += adapters.vale.run(files, cfg)
    if cfg.checks.enable_codespell:
        issues += adapters.codespell.run(files, cfg)
    issues += adapters.languagetool.run(files, cfg, url_env="LT_URL")

    run_llm = args.with_llm and not args.fast
    if args.cmd == "review-fix":
        run_llm = True
    if args.cmd == "review-auto":
        run_llm = True

    if run_llm:
        segments = extract_segments(files, cfg)
        if cfg.llm.provider == "ollama":
            issues += adapters.ollama.run(segments, cfg, url_env="OLLAMA_URL")
        elif cfg.llm.provider in ("openai", "lm-studio"):
            issues += adapters.openai.run(segments, cfg, url_env="OPENAI_URL")

    if args.cmd == "review-fix":
        normalized = [normalize(issue) for issue in issues]
        active = apply_suppressions(normalized)
        summary = summarize(active)
        result = {"version": "1.0", "summary": summary, "issues": normalized}
        output_json(result, args.json_out)
        from .fixer import apply_fixes_from_issues, annotate_llm_comments
        apply_fixes_from_issues(active, cfg)
        annotate_llm_comments(active, cfg, files=[str(p) for p in files])
    elif args.cmd == "review-auto":
        from .adjudicate import adjudicate_issues
        from .fixer import apply_adjudicated_fixes, annotate_llm_comments, apply_fixes_from_issues
        normalized = [normalize(issue) for issue in issues]
        active = apply_suppressions(normalized)
        adjudicated = adjudicate_issues(active, cfg)
        apply_adjudicated_fixes(adjudicated)
        accepted_non_llm = [
            issue for issue in adjudicated
            if issue.get("tool") != "llm"
            and (issue.get("adjudication") or {}).get("accept")
        ]
        apply_fixes_from_issues(accepted_non_llm, cfg)
        llm_issues = [i for i in adjudicated if i.get("tool") == "llm"]
        annotate_llm_comments(llm_issues, cfg, files=[str(p) for p in files])
        accepted = []
        for issue in adjudicated:
            if issue.get("tool") == "llm":
                accepted.append(issue)
                continue
            decision = issue.get("adjudication")
            if decision and decision.get("accept"):
                accepted.append(issue)
        summary = summarize(accepted)
        result = {"version": "1.0", "summary": summary, "issues": normalized}
        output_json(result, args.json_out)
    else:
        normalized = [normalize(issue) for issue in issues]
        active = apply_suppressions(normalized)
        summary = summarize(active)
        result = {"version": "1.0", "summary": summary, "issues": normalized}
        output_json(result, args.json_out)

    if summary["errors"] > 0:
        sys.exit(2)
    if summary["warnings"] > 0:
        sys.exit(1)
    sys.exit(0)


def resolve_files(files: Sequence[str] | None, cfg: ClaraConfig) -> List[Path]:
    if files:
        return [Path(f) for f in files]
    return discover(cfg)


def discover(cfg: ClaraConfig, root: Path | None = None) -> List[Path]:
    root = root or Path(".")
    candidates: set[Path] = set()
    for pattern in cfg.paths.include:
        candidates.update(p for p in root.glob(pattern) if p.is_file())
    filtered = [
        p for p in candidates if not _is_excluded(p, cfg.paths.exclude, root=root)
    ]
    return sorted(filtered)


def _is_excluded(path: Path, patterns: Iterable[str], root: Path) -> bool:
    rel = path.relative_to(root)
    rel_str = str(rel)
    for pattern in patterns:
        if fnmatch.fnmatch(rel_str, pattern):
            return True
        # Handle directory globs manually (e.g., out/**)
        if pattern.endswith("/**") and rel_str.startswith(pattern[:-3]):
            return True
    return False


def output_json(payload: dict, destination: str | None) -> None:
    if destination:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
