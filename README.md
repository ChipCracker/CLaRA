# CLaRA – Continuous LaTeX Review Assistant

CLaRA is an offline-first, containerized toolchain for continuously reviewing LaTeX projects while you write. It bundles multiple specialized tools (formatting, linting, grammar, and style checks) behind a single workflow and emits a normalized JSON report that is suitable for automation and traceability.

The core idea is simple: keep inputs versioned (LaTeX sources + configuration), run the checks reproducibly (via containers), and produce stable artifacts (`out/check.json`, `out/review.json`) that both humans and tooling can consume.

## What it does

- **Fast checks** for frequent feedback while editing (hook-equivalent mode).
- **Full review pipeline** for deeper runs: checks + optional LLM-assisted review + auto-fix + annotation.
- **Normalized JSON outputs** with per-issue metadata (tool, location, severity, message, optional suggestion/fix).
- **Suppressions via LaTeX comments** so known false positives don't block you while preserving traceability.

## Project Structure

```
CLaRA/
├── tex/                      # LaTeX source files
│   ├── main.tex              # Main document
│   └── sections/             # Document sections
│       └── unter.tex
├── src/clara/                # Python source code
│   ├── cli.py                # CLI entrypoint
│   ├── config.py             # Configuration loading (clara.toml)
│   ├── extract.py            # Text extraction from LaTeX
│   ├── fixer.py              # Auto-fix logic
│   ├── adjudicate.py         # LLM-based issue adjudication
│   ├── prompts.py            # Prompt templates for LLM
│   ├── report.py             # Report generation and normalization
│   ├── suppressions.py       # Suppression comment handling
│   └── adapters/             # Tool adapters
│       ├── chktex.py         # ChkTeX LaTeX linter
│       ├── codespell.py      # Spell checker
│       ├── languagetool.py   # Grammar checker
│       ├── latexindent.py    # LaTeX formatter
│       ├── ollama.py         # Ollama LLM adapter
│       ├── openai.py         # OpenAI/LM Studio adapter
│       └── vale.py           # Style/prose linter
├── configs/                  # Tool configurations
│   ├── .chktexrc             # ChkTeX settings
│   ├── .latexindent.yaml     # latexindent settings
│   ├── vale.ini              # Vale configuration
│   ├── languagetool.json     # LanguageTool rules/settings
│   ├── prompt_*.txt          # LLM prompts (en/de)
│   └── styles/               # Vale custom styles
├── docker/                   # Dockerfiles
│   ├── core.Dockerfile       # Main CLaRA container
│   └── languagetool.Dockerfile
├── hooks/                    # Git hooks
│   └── pre-commit            # Pre-commit check script
├── scripts/                  # Utility scripts
│   ├── install-hooks.sh      # Install git hooks
│   └── uninstall-hooks.sh    # Remove git hooks
├── tests/                    # Test suite
├── out/                      # Generated outputs (git-ignored)
│   ├── check.json            # Fast check results
│   └── review.json           # Full review results
├── clara.toml                # Main configuration
├── compose.yaml              # Docker Compose services
└── Makefile                  # Build and workflow targets
```

## Toolchain

Depending on configuration, CLaRA orchestrates:

| Tool | Purpose | Adapter |
|------|---------|---------|
| `latexindent` | LaTeX formatting | `adapters/latexindent.py` |
| `ChkTeX` | LaTeX linting | `adapters/chktex.py` |
| `Vale` | Style/terminology checks | `adapters/vale.py` |
| `codespell` | Spelling (optional) | `adapters/codespell.py` |
| `LanguageTool` | Grammar checking | `adapters/languagetool.py` |
| Ollama / OpenAI | LLM-assisted review | `adapters/ollama.py`, `adapters/openai.py` |

## Outputs

- `out/check.json`: fast-check artifact (expected to be cheap to run frequently).
- `out/review.json`: full workflow artifact; includes issues, suppressions, and applied fixes/decisions where available.

Suppressed findings are excluded from headline counts/exit codes, but they remain present in JSON (e.g. `suppressed: true`) so downstream tooling can still see what happened.

## Prerequisites

- Docker
- Docker Compose

## Quickstart

```bash
# Start services (LanguageTool, Ollama)
make up

# Run full review pipeline (recommended)
make review-auto

# Stop services
make down
```

## CLI Commands

CLaRA provides several commands via `python -m clara.cli <command>`:

| Command | Description |
|---------|-------------|
| `review-auto` | **Main workflow**: format, lint, grammar check, LLM review, auto-fix, and annotate |
| `check` | Fast checks only (no LLM) – suitable for pre-commit hooks |
| `fix` | Run `latexindent` formatting only |
| `fix-content` | Apply fixes from a JSON issues file |
| `annotate` | Add LLM comments to source files |
| `review-fix` | Full review with fixes but without adjudication |

### Exit Codes

- `0`: No issues
- `1`: Warnings found
- `2`: Errors found

## Makefile Targets

| Target | Description |
|--------|-------------|
| `make up` | Start Docker services |
| `make down` | Stop Docker services |
| `make review-auto` | Run full review pipeline |
| `make review` | Alias for `review-auto` |
| `make check` | Fast check (hook-equivalent) |
| `make fix` | Format LaTeX files |
| `make fix-content` | Apply AI-suggested fixes |
| `make annotate` | Add LLM annotations |
| `make build` | Compile LaTeX to PDF (via tectonic) |
| `make clean` | Remove outputs and backups |
| `make report` | Pretty-print `out/review.json` |
| `make pull` | Pull/update Ollama model |

Debug variants (`debug-*`) show more verbose output.

## Configuration

Central configuration lives in `clara.toml`:

```toml
[languages]
primary = "en-US"
secondary = ["de-DE"]

[llm]
provider = "ollama"       # or "openai" / "lm-studio"
model = "qwen3:4b"
max_tokens = 256
temperature = 0.2
timeout_seconds = 600

[checks]
enable_codespell = false
severity_threshold = "warning"

[paths]
include = ["tex/**/*.tex", "tex/**/*.bib"]
exclude = ["build/**", "out/**", "vendor/**"]
```

Tool-specific configs are in `configs/`:

- `.chktexrc` – ChkTeX rule configuration
- `.latexindent.yaml` – Formatting rules
- `vale.ini` – Vale configuration
- `languagetool.json` – Disabled rules, language settings
- `prompt_*.txt` – LLM prompts for different tasks and languages

## Git Hooks

CLaRA includes a pre-commit hook that runs fast checks on staged `.tex` and `.bib` files:

```bash
# Install hooks
./scripts/install-hooks.sh

# Uninstall hooks
./scripts/uninstall-hooks.sh
```

The hook runs `make check` on staged files and blocks commits if errors are found.

## Suppressions

Use LaTeX comments to suppress findings:

```tex
% clara: ignore-next-line
This line will be ignored.

% clara: ignore-start
This entire block
will be ignored.
% clara: ignore-end

% clara: ignore-file
```

Suppressions apply across all tools. They're designed to enable adoption without losing traceability: suppressed findings remain in JSON but do not affect headline counts or exit codes.

## LLM Integration

CLaRA supports local LLM servers for semantic review:

### Ollama

```toml
[llm]
provider = "ollama"
model = "qwen3:4b"
```

### LM Studio / OpenAI-compatible

```toml
[llm]
provider = "lm-studio"
model = "nvidia/nemotron-3-nano"
api_url = "http://host.docker.internal:1234/v1"
```

The LLM is used for:
- **Clarity review**: Suggesting improvements to prose
- **Adjudication**: Deciding whether tool-reported issues are real problems

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        CLI (cli.py)                         │
├─────────────────────────────────────────────────────────────┤
│  discover files → run adapters → normalize → suppress →     │
│  adjudicate (LLM) → fix → annotate → output JSON            │
├─────────────────────────────────────────────────────────────┤
│                       Adapters Layer                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│  │ ChkTeX   │ │  Vale    │ │ LangTool │ │  LLM     │        │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘        │
├─────────────────────────────────────────────────────────────┤
│                    Docker Services                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │     Core     │  │ LanguageTool │  │    Ollama    │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

## Development

```bash
# Run tests
pytest tests/

# Type checking
mypy src/

# Linting
ruff check src/
```
