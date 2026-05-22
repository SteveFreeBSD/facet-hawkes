"""Configuration helpers for local ethnos runs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OllamaThink: TypeAlias = bool | Literal["low", "medium", "high"] | None


@dataclass(frozen=True)
class Settings:
    db_path: Path
    ollama_host: str
    ollama_model: str
    ollama_timeout: float
    ollama_structure_num_predict: int
    ollama_answer_num_predict: int
    ollama_num_ctx: int
    ollama_think: OllamaThink
    prompt_path: Path


def parse_ollama_think(value: str | None) -> OllamaThink:
    if value is None:
        return False
    normalized = value.strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    if normalized in ("", "auto", "default", "none", "omit"):
        return None
    if normalized in ("low", "medium", "high"):
        return normalized
    raise ValueError(
        "ETHNOS_OLLAMA_THINK must be one of false, true, auto, low, medium, or high"
    )


def load_settings() -> Settings:
    db_path = Path(os.getenv("ETHNOS_DB_PATH", PROJECT_ROOT / "data" / "ethnos.sqlite"))
    prompt_path = Path(
        os.getenv("ETHNOS_TOPIC_PROMPT", PROJECT_ROOT / "prompts" / "topic_extraction.md")
    )
    return Settings(
        db_path=db_path,
        ollama_host=os.getenv("ETHNOS_OLLAMA_HOST", "http://localhost:11434"),
        ollama_model=os.getenv("ETHNOS_OLLAMA_MODEL", "gemma-python"),
        ollama_timeout=float(os.getenv("ETHNOS_OLLAMA_TIMEOUT", "300")),
        ollama_structure_num_predict=int(
            os.getenv(
                "ETHNOS_OLLAMA_STRUCTURE_NUM_PREDICT",
                os.getenv("ETHNOS_OLLAMA_NUM_PREDICT", "2048"),
            )
        ),
        ollama_answer_num_predict=int(
            os.getenv(
                "ETHNOS_OLLAMA_ANSWER_NUM_PREDICT",
                os.getenv("ETHNOS_OLLAMA_NUM_PREDICT", "1536"),
            )
        ),
        ollama_num_ctx=int(os.getenv("ETHNOS_OLLAMA_NUM_CTX", "8192")),
        ollama_think=parse_ollama_think(os.getenv("ETHNOS_OLLAMA_THINK")),
        prompt_path=prompt_path,
    )
