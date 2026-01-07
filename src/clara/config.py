from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field
import tomllib


class PathsConfig(BaseModel):
    include: List[str] = Field(default_factory=list)
    exclude: List[str] = Field(default_factory=list)


class ChecksConfig(BaseModel):
    enable_codespell: bool = False
    severity_threshold: str = "warning"


class LLMConfig(BaseModel):
    provider: str = "ollama"
    model: str = "mistral"
    api_url: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    timeout_seconds: Optional[int] = 120


class LanguagesConfig(BaseModel):
    primary: str = "de-DE"
    secondary: List[str] = Field(default_factory=list)


class FixerConfig(BaseModel):
    safety_ratio: float = Field(default=0.85, ge=0.0, le=1.0)
    max_length_delta_ratio: float = Field(default=0.15, ge=0.0, le=1.0)


class ClaraConfig(BaseModel):
    languages: LanguagesConfig
    llm: LLMConfig
    checks: ChecksConfig
    paths: PathsConfig
    fixer: FixerConfig = Field(default_factory=FixerConfig)


def load_config(path: str | Path) -> ClaraConfig:
    """Load configuration from TOML file."""
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    return ClaraConfig.model_validate(data)
