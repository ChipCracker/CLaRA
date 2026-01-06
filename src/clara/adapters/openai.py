from __future__ import annotations

import json
import os
import httpx
from typing import Iterable, List

from ..extract import Segment
from ..prompts import load_prompt


def run(segments: Iterable[Segment], cfg, url_env: str | None = None) -> List[dict]:
    """Run LLM checks via OpenAI-compatible API (e.g. LM Studio)."""
    # Use config api_url if provided, else check env, else default LM Studio
    base_url = cfg.llm.api_url or os.getenv(url_env, "http://localhost:1234/v1")
    url = f"{base_url.rstrip('/')}/chat/completions"

    system_prompt = load_prompt("prompt_clarity", cfg, default="You are a helpful editor.")

    issues = []

    for seg in segments:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": seg.text},
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

        try:
            # We don't use API key for local LM Studio by default
            headers = {}
            api_key = os.getenv("OPENAI_API_KEY")
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            timeout = cfg.llm.timeout_seconds or 60
            resp = httpx.post(url, json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()
            result = resp.json()
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            suggestions = None
            # Parse JSON from content
            try:
                suggestions = json.loads(content)
            except json.JSONDecodeError:
                # Try to extract JSON list if model included extra text (e.g. thinking blocks)
                try:
                    start = content.index('[')
                    end = content.rindex(']') + 1
                    suggestions = json.loads(content[start:end])
                except (ValueError, json.JSONDecodeError):
                    # If extraction fails, log and skip
                    pass

            if suggestions:
                # Should be a list of dicts (the prompt asks for a list)
                # Sometimes OpenAI returns { "suggestions": [...] }
                if isinstance(suggestions, dict) and "suggestions" in suggestions:
                    suggestions = suggestions["suggestions"]
                
                if isinstance(suggestions, list):
                    for item in suggestions:
                        if isinstance(item, str):
                            issues.append({
                                "tool": "llm",
                                "type": "clarity",
                                "file": seg.file,
                                "line": seg.start_line,
                                "severity": "note",
                                "message": "Suggestion",
                                "suggestion": item,
                            })
                            continue
                        issues.append({
                            "tool": "llm",
                            "type": "clarity",
                            "file": seg.file,
                            "line": seg.start_line,
                            "severity": "note",
                            "message": item.get("rationale", "Suggestion"),
                            "suggestion": item.get("suggestion", ""),
                        })

        except Exception as e:
            issues.append({
                "tool": "llm",
                "severity": "error",
                "message": f"OpenAI/LMStudio error: {str(e)}"
            })
            
    return issues
