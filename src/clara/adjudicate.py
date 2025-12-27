from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import httpx

from .config import ClaraConfig


def adjudicate_issues(issues: Iterable[Dict[str, Any]], cfg: ClaraConfig) -> List[Dict[str, Any]]:
    """Use LLM to accept/reject tool issues and optionally provide fixes."""
    prompt_path = Path("configs/prompt_adjudicate.txt")
    system_prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""

    results: List[Dict[str, Any]] = []
    for issue in issues:
        if issue.get("tool") == "llm":
            results.append(issue)
            continue

        file_path = issue.get("file")
        line_no = int(issue.get("line", 0) or 0)
        line_text = _read_line(file_path, line_no)

        decision = _call_adjudicator(issue, line_text, cfg, system_prompt)
        issue["adjudication"] = decision
        results.append(issue)
    return results


def _read_line(file_path: str | None, line_no: int) -> str:
    if not file_path or line_no <= 0:
        return ""
    try:
        lines = Path(file_path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return ""
    if line_no > len(lines):
        return ""
    return lines[line_no - 1]


def _call_adjudicator(issue: Dict[str, Any], line_text: str, cfg: ClaraConfig, system_prompt: str) -> Dict[str, Any]:
    payload = {
        "issue": {
            "tool": issue.get("tool"),
            "type": issue.get("type"),
            "message": issue.get("message"),
            "code": issue.get("code"),
            "suggestion": issue.get("suggestion"),
        },
        "line": line_text,
    }
    user_msg = json.dumps(payload, ensure_ascii=False)

    if cfg.llm.provider == "ollama":
        content = _call_ollama(system_prompt, user_msg, cfg)
    else:
        content = _call_openai(system_prompt, user_msg, cfg)

    decision = _parse_json_object(content)
    if decision is None:
        decision = {"accept": True}

    # Some models comply with JSON but omit "fix" even for clear SPELLER_RULE cases.
    # Retry once with a stricter prompt asking only for an explicit fix.
    if _needs_spellcheck_fix(issue, decision):
        retry = _call_spellcheck_fix_only(issue, line_text, cfg)
        if retry is not None:
            return retry

    return decision


def _needs_spellcheck_fix(issue: Dict[str, Any], decision: Dict[str, Any]) -> bool:
    if issue.get("tool") != "languagetool":
        return False
    code = str(issue.get("code") or "")
    if not code.endswith("SPELLER_RULE"):
        return False
    if not issue.get("suggestion"):
        return False
    if decision.get("accept") is not True:
        return False
    fix = decision.get("fix")
    return not (isinstance(fix, str) and fix.strip())


def _call_spellcheck_fix_only(issue: Dict[str, Any], line_text: str, cfg: ClaraConfig) -> Dict[str, Any] | None:
    system_prompt = (
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
    payload = {
        "code": issue.get("code"),
        "suggestion": issue.get("suggestion"),
        "line": line_text,
    }
    user_msg = json.dumps(payload, ensure_ascii=False)

    try:
        if cfg.llm.provider == "ollama":
            content = _call_ollama(system_prompt, user_msg, cfg)
        else:
            content = _call_openai(system_prompt, user_msg, cfg)
    except Exception:
        return None

    decision = _parse_json_object(content)
    if decision is None:
        return None
    fix = decision.get("fix")
    if decision.get("accept") is True and isinstance(fix, str) and fix.strip():
        return decision
    return None


def _call_openai(system_prompt: str, user_msg: str, cfg: ClaraConfig) -> str:
    base_url = cfg.llm.api_url or os.getenv("OPENAI_URL", "http://localhost:1234/v1")
    url = f"{base_url.rstrip('/')}/chat/completions"
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]
    payload = {
        "model": cfg.llm.model,
        "messages": messages,
        "stream": False,
    }
    if cfg.llm.temperature is not None:
        payload["temperature"] = cfg.llm.temperature
    if cfg.llm.max_tokens is not None:
        payload["max_tokens"] = cfg.llm.max_tokens

    headers = {}
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    timeout = cfg.llm.timeout_seconds or 60
    resp = httpx.post(url, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    result = resp.json()
    return result.get("choices", [{}])[0].get("message", {}).get("content", "")


def _call_ollama(system_prompt: str, user_msg: str, cfg: ClaraConfig) -> str:
    base_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
    chat_url = f"{base_url.rstrip('/')}/api/chat"
    generate_url = f"{base_url.rstrip('/')}/api/generate"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    options: Dict[str, Any] = {}
    if cfg.llm.temperature is not None:
        options["temperature"] = cfg.llm.temperature
    if cfg.llm.max_tokens is not None:
        options["num_predict"] = cfg.llm.max_tokens

    timeout = cfg.llm.timeout_seconds or 60

    # Prefer /api/chat, but fall back to /api/generate for older Ollama versions.
    chat_payload: Dict[str, Any] = {
        "model": cfg.llm.model,
        "messages": messages,
        "stream": False,
        "format": "json",
    }
    if options:
        chat_payload["options"] = options

    try:
        resp = httpx.post(chat_url, json=chat_payload, timeout=timeout)
        resp.raise_for_status()
        result = resp.json()
        return result.get("message", {}).get("content", "")
    except httpx.HTTPStatusError as e:
        if e.response is None or e.response.status_code != 404:
            raise

    prompt = f"{system_prompt}\n\n{user_msg}\n"
    gen_payload: Dict[str, Any] = {
        "model": cfg.llm.model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
    }
    if options:
        gen_payload["options"] = options

    resp = httpx.post(generate_url, json=gen_payload, timeout=timeout)
    resp.raise_for_status()
    result = resp.json()
    return result.get("response", "")


def _parse_json_object(content: str) -> Dict[str, Any] | None:
    if not content:
        return None
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    try:
        start = content.index("{")
        end = content.rindex("}") + 1
        data = json.loads(content[start:end])
        if isinstance(data, dict):
            return data
    except (ValueError, json.JSONDecodeError):
        return None
    return None
