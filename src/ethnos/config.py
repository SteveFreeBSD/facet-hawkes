"""Configuration helpers for local ethnos runs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    db_path: Path
    ollama_host: str
    ollama_model: str
    ollama_timeout: float
    ollama_num_predict: int
    prompt_path: Path


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
        ollama_num_predict=int(os.getenv("ETHNOS_OLLAMA_NUM_PREDICT", "2048")),
        prompt_path=prompt_path,
    )
