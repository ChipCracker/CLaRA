# CLaRA – Continuous LaTeX Review Assistant

Dieses Projekt bündelt Formatierungs- und Qualitätschecks für LaTeX-Dokumente in einer offline betriebenen Toolchain.

## Konfiguration

- `clara.toml` – zentrale Einstellungen (Sprachen, LLM-Parameter, Pfadfilter, Schwellwerte).
- `configs/vale.ini` – Vale-Konfiguration, verweist auf `configs/styles/`.
- `configs/styles/CLaRA/*.yml` – projektspezifische Vale-Regeln (aktuell ein Minimal-Stub).
- `configs/.chktexrc` – deaktivierte Warnungen für chktex.
- `configs/.latexindent.yaml` – Formatierungsvorgaben für latexindent.
- `configs/languagetool.json` – deaktivierte Regeln und Spracheinstellungen für LanguageTool.
- `configs/prompt_clarity.txt` – Prompt für das LLM im Review-Workflow.

## Schnellstart

- `make review-auto` – Standard-Workflow (Checks + LLM + Auto-Fix + Annotationen, JSON unter `out/review.json`).
- `make review` – Alias für `make review-auto`.
- `make debug-check` – schnelle Checks ohne LLM (Hook-Äquivalent; Debug/Diagnose).
- `make debug-review-fix`, `make debug-fix-content`, `make debug-annotate`, `make debug-fix` – Debug/Diagnose-Workflows.
- Legacy-Aliases bleiben verfügbar: `make check`, `make review-fix`, `make fix-content`, `make annotate`, `make fix`.

## Suppressions (grob)

Suppressions gelten für alle Tools (kein Tool-Selector). LaTeX-Kommentare:

```tex
% clara: ignore-next-line
% clara: ignore-start
% clara: ignore-end
% clara: ignore-file
```

Suppressede Issues fließen nicht in Summary/Exit-Code ein, bleiben aber im JSON (mit `suppressed: true`).

Weitere Details stehen in `AGENTS.md` und den Aufgabenlisten unter `todo/`.
