from __future__ import annotations

from pathlib import Path

from .config import ClaraConfig


def is_english(cfg: ClaraConfig) -> bool:
    primary = (cfg.languages.primary or "").strip().lower()
    return primary.startswith("en")


def load_prompt(basename: str, cfg: ClaraConfig, default: str = "") -> str:
    """
    Load a prompt file, selecting an English variant when primary language is en-*.
    Falls back to the non-suffixed prompt if the localized file is missing.
    """
    suffix = "_en" if is_english(cfg) else ""
    candidate = Path(f"configs/{basename}{suffix}.txt")
    if not candidate.exists() and suffix:
        candidate = Path(f"configs/{basename}.txt")
    if candidate.exists():
        return candidate.read_text(encoding="utf-8")
    return default


def spellcheck_fix_prompt(cfg: ClaraConfig) -> str:
    if is_english(cfg):
        return (
            "Role: Proofreader.\n"
            "Goal: Fix spelling mistakes.\n"
            "Output: Exactly one JSON object:\n"
            '{ "accept": true, "fix": "...", "comment": "..." }\n'
            "Rules:\n"
            "- accept must be true.\n"
            "- fix is the full corrected line (not empty).\n"
            "- Only change a single word in the line, based on the suggestions.\n"
            "- If multiple suggestions fit, pick the shortest plausible one.\n"
            "- Example: In 'The ___ is an example.' choose 'is' over 'iss'.\n"
            "- No extra text.\n"
        )
    return (
        "Rolle: Korrektor.\n"
        "Ziel: Rechtschreibfehler beheben.\n"
        "Ausgabe: Genau ein JSON-Objekt:\n"
        '{ "accept": true, "fix": "...", "comment": "..." }\n'
        "Regeln:\n"
        "- accept muss true sein.\n"
        "- fix ist die komplette korrigierte Zeile (nicht leer).\n"
        "- Ändere ausschließlich ein einzelnes Wort in der Zeile, basierend auf den Suggestions.\n"
        "- Wenn mehrere Suggestions passen: wähle die kürzeste plausible Suggestion.\n"
        "- Beispiel: In 'Das ___ ein Beispiel.' ist 'ist' plausibler als 'isst'.\n"
        "- Keine Zusatztexte.\n"
    )
