from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from .config import ClaraConfig, load_config
from .extract import extract_segments
from .report import normalize, summarize
from .suppressions import apply_suppressions
from . import adapters
from .cache import (
    ReviewCache,
    analyze_file_changes,
    build_cache_from_results,
    get_cached_issues_for_unchanged,
    get_cached_llm_issues,
    get_lines_needing_check,
    load_cache,
    save_cache,
    DEFAULT_CACHE_PATH,
)


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

    # Load cache for review-auto (automatic incremental mode)
    cache: Optional[ReviewCache] = None
    if args.cmd == "review-auto":
        cache = load_cache(DEFAULT_CACHE_PATH)
        if cache:
            print(f"[cache] Loaded cache with {len(cache.files)} file(s)")

    # Run checks (incremental if cache exists, otherwise full)
    if args.cmd == "review-auto" and cache:
        issues = run_incremental_checks(files, cfg, cache)
    else:
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
    if args.cmd == "review-auto" and not cache:
        run_llm = True

    # Track all segments for cache building (even if LLM doesn't run)
    all_segments = extract_segments(files, cfg) if run_llm or args.cmd == "review-auto" else []

    if run_llm:
        # Filter segments using cache for incremental LLM review
        fresh_segments = all_segments
        if cache:
            fresh_segments = []
            for file_path in files:
                file_key = str(file_path)
                file_segments = [s for s in all_segments if s.file == file_key]
                cached_file = cache.files.get(file_key)
                new_segs, cached_iss = get_cached_llm_issues(file_segments, cached_file)
                fresh_segments.extend(new_segs)
                issues.extend(cached_iss)
            if fresh_segments:
                print(f"[cache] LLM reviewing {len(fresh_segments)} of {len(all_segments)} segment(s)")
            else:
                print(f"[cache] All {len(all_segments)} segment(s) cached, skipping LLM")

        if fresh_segments:
            if cfg.llm.provider == "ollama":
                issues += adapters.ollama.run(fresh_segments, cfg, url_env="OLLAMA_URL")
            elif cfg.llm.provider in ("openai", "lm-studio"):
                issues += adapters.openai.run(fresh_segments, cfg, url_env="OPENAI_URL")

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
        # Save cache for incremental mode (include segments for LLM caching)
        new_cache = build_cache_from_results(files, normalized, all_segments)
        save_cache(new_cache, DEFAULT_CACHE_PATH)
        print(f"[cache] Saved cache for {len(files)} file(s), {len(all_segments)} segment(s)")
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


def run_incremental_checks(
    files: List[Path],
    cfg: ClaraConfig,
    cache: Optional[ReviewCache],
) -> List[Dict[str, Any]]:
    """Run checks incrementally, using cache for unchanged lines."""
    all_issues: List[Dict[str, Any]] = []
    files_to_check: List[Path] = []
    file_changes: Dict[str, List[Any]] = {}
    cached_files: Dict[str, Any] = {}

    # Phase 1: Analyze all files for changes
    for file_path in files:
        changes, cached_file, needs_check = analyze_file_changes(file_path, cache)

        if not needs_check and cached_file:
            # File unchanged - load all issues from cache
            cached_count = 0
            for line_no, cached_line in cached_file.lines.items():
                for issue in cached_line.issues:
                    all_issues.append(issue.to_full_issue(str(file_path), line_no))
                    cached_count += 1
            print(f"[cache] {file_path}: unchanged, {cached_count} cached issues")
        else:
            files_to_check.append(file_path)
            file_changes[str(file_path)] = changes
            if cached_file:
                cached_files[str(file_path)] = cached_file

    if not files_to_check:
        print("[cache] No changes detected, using cached results.")
        return all_issues

    print(f"[cache] Checking {len(files_to_check)} changed file(s)...")

    # Phase 2: Run adapters on files that need checking
    fresh_issues: List[Dict[str, Any]] = []
    fresh_issues += adapters.latexindent.run(files_to_check, cfg)
    fresh_issues += adapters.chktex.run(files_to_check, cfg)
    fresh_issues += adapters.vale.run(files_to_check, cfg)
    if cfg.checks.enable_codespell:
        fresh_issues += adapters.codespell.run(files_to_check, cfg)
    fresh_issues += adapters.languagetool.run(files_to_check, cfg, url_env="LT_URL")

    # Phase 3: Filter fresh issues and merge with cached
    for file_path in files_to_check:
        path_str = str(file_path)
        changes = file_changes.get(path_str, [])
        cached_file = cached_files.get(path_str)
        changed_lines = get_lines_needing_check(changes)

        # Fresh issues for changed lines only
        fresh_count = 0
        for issue in fresh_issues:
            if issue.get("file") == path_str and issue.get("line") in changed_lines:
                all_issues.append(issue)
                fresh_count += 1

        # Cached issues for unchanged lines
        cached_count = 0
        if cached_file:
            cached_issues = get_cached_issues_for_unchanged(path_str, changes, cached_file)
            all_issues.extend(cached_issues)
            cached_count = len(cached_issues)

        print(f"[cache] {file_path}: {fresh_count} new, {cached_count} cached")

    return all_issues


if __name__ == "__main__":
    main()
