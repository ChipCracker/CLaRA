from __future__ import annotations

import json
import os
import httpx
from typing import Iterable, List

from ..extract import Segment
from ..prompts import load_prompt


def run(segments: Iterable[Segment], cfg, url_env: str | None = None) -> List[dict]:
    """Run LLM checks via Ollama."""
    base_url = os.getenv(url_env, "http://localhost:11434") if url_env else "http://localhost:11434"
    chat_url = f"{base_url.rstrip('/')}/api/chat"
    generate_url = f"{base_url.rstrip('/')}/api/generate"

    system_prompt = load_prompt("prompt_clarity", cfg, default="You are a helpful editor.")

    issues = []

    for seg in segments:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": seg.text},
        ]
        
        options = {}
        if cfg.llm.temperature is not None:
            options["temperature"] = cfg.llm.temperature
        if cfg.llm.max_tokens is not None:
            options["num_predict"] = cfg.llm.max_tokens

        chat_payload = {
            "model": cfg.llm.model,
            "messages": messages,
            "stream": False,
            "format": "json",
        }
        
        if options:
            chat_payload["options"] = options

        try:
            timeout = cfg.llm.timeout_seconds or 60
            try:
                resp = httpx.post(chat_url, json=chat_payload, timeout=timeout)
                resp.raise_for_status()
                result = resp.json()
                content = result.get("message", {}).get("content", "")
            except httpx.HTTPStatusError as e:
                # Older Ollama versions don't have /api/chat; fall back to /api/generate.
                if e.response is None or e.response.status_code != 404:
                    raise
                prompt = f"{system_prompt}\n\n{seg.text}\n"
                gen_payload = {
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
                content = result.get("response", "")
            
            # Parse JSON from content
            suggestions = _parse_json_list(content)
            for item in suggestions:
                if not isinstance(item, dict):
                    continue
                issues.append({
                    "tool": "llm",
                    "type": "clarity",
                    "file": seg.file,
                    "line": seg.start_line,  # logical start of chunk
                    "severity": "note",
                    "message": item.get("rationale", "Suggestion"),
                    "suggestion": item.get("suggestion", ""),
                })

        except Exception as e:
            issues.append({
                "tool": "llm",
                "severity": "error",
                "message": f"Ollama error: {str(e)}"
            })
            
    return issues


def _parse_json_list(content: str) -> list:
    if not content:
        return []
    try:
        data = json.loads(content)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("items", "suggestions", "results"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
    except json.JSONDecodeError:
        pass

    # Try to recover the first JSON array from a response with extra text / fences.
    try:
        start = content.index("[")
        end = content.rindex("]") + 1
        data = json.loads(content[start:end])
        return data if isinstance(data, list) else []
    except (ValueError, json.JSONDecodeError):
        return []
