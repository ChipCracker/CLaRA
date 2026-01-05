# CLaRA – Continuous LaTeX Review Assistant

CLaRA is an offline-first, containerized toolchain for continuously reviewing LaTeX projects while you write. It bundles multiple specialized tools (formatting, linting, grammar, and style checks) behind a single workflow and emits a normalized JSON report that is suitable for automation and traceability.

The core idea is simple: keep inputs versioned (LaTeX sources + configuration), run the checks reproducibly (via containers), and produce stable artifacts (`out/check.json`, `out/review.json`) that both humans and tooling can consume.

## What it does

- **Fast checks** for frequent feedback while editing (hook-equivalent mode).
- **Full review pipeline** for deeper runs: checks + optional LLM-assisted review + auto-fix + annotation.
- **Normalized JSON outputs** with per-issue metadata (tool, location, severity, message, optional suggestion/fix).
- **Suppressions via LaTeX comments** so known false positives don’t block you while preserving traceability.

## Toolchain (today)

Depending on configuration, CLaRA orchestrates:

- `latexindent` (formatting)
- `ChkTeX` (LaTeX lint)
- `Vale` (style/terminology)
- optional `codespell`
- `LanguageTool` (grammar; service)
- optional semantic review via a local LLM server (e.g. Ollama or an OpenAI-compatible API endpoint)

## Outputs

- `out/check.json`: fast-check artifact (expected to be cheap to run frequently).
- `out/review.json`: full workflow artifact; includes issues, suppressions, and applied fixes/decisions where available.

Suppressed findings are excluded from headline counts/exit codes, but they remain present in JSON (e.g. `suppressed: true`) so downstream tooling can still see what happened.

## Quickstart (Docker)

Prerequisites: Docker + Docker Compose.

- Start services: `make up`
- Fast check (hook-equivalent): `make check` (writes `out/check.json`)
- Full workflow (default): `make review-auto` (writes `out/review.json`)
- Stop services: `make down`

Useful debug targets:

- `make debug-check`
- `make debug-review-fix`
- `make debug-fix-content`
- `make debug-annotate`
- `make debug-fix`

## Configuration

Central configuration lives in `clara.toml` (languages, LLM provider/model, path filters, severity threshold, etc.). Tool-specific configs are in `configs/`.

Example (excerpt):

```toml
[languages]
primary = "de-DE"
secondary = ["en-US"]

[llm]
provider = "ollama" # or "openai" / "lm-studio" / "ollama"
model = "qwen3:4b"
max_tokens = 256
temperature = 0.2
timeout_seconds = 600

[checks]
enable_codespell = false
severity_threshold = "warning"

[paths]
include = ["**/*.tex", "**/*.bib"]
exclude = ["build/**", "out/**", "vendor/**", "test_hook.tex"]
```

## Suppressions

Use LaTeX comments to suppress findings:

```tex
% clara: ignore-next-line
% clara: ignore-start
% clara: ignore-end
% clara: ignore-file
```

Suppressions apply across tools (no tool selector). They’re designed to enable adoption without losing traceability: suppressed findings remain in JSON but do not affect headline counts or exit codes.
