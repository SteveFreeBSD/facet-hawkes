"""Configuration helpers for local ethnos runs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OLLAMA_KEEP_ALIVE = "30m"
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
    ollama_vision_model: str
    ollama_vision_verifier_model: str
    ollama_vision_num_predict: int
    ollama_math_model: str
    question_image_cache_dir: Path
    question_capture_dir: Path
    agent_model: str | None
    agent_model_profile: str
    agent_allow_web: bool
    agent_vision_pages: str
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
        os.getenv(
            "ETHNOS_TOPIC_PROMPT", PROJECT_ROOT / "prompts" / "topic_extraction.md"
        )
    )
    return Settings(
        db_path=db_path,
        ollama_host=os.getenv("ETHNOS_OLLAMA_HOST", "http://localhost:11434"),
        ollama_model=os.getenv("ETHNOS_OLLAMA_MODEL", "qwen3.5:9b"),
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
        ollama_num_ctx=int(os.getenv("ETHNOS_OLLAMA_NUM_CTX", "4096")),
        ollama_think=parse_ollama_think(os.getenv("ETHNOS_OLLAMA_THINK")),
        ollama_vision_model=os.getenv("ETHNOS_OLLAMA_VISION_MODEL", "qwen3.5:4b"),
        # A *different* reader from the primary above, on purpose: two readings
        # of one picture are only worth having when one model cannot merely
        # repeat its own symbol mistake.
        ollama_vision_verifier_model=os.getenv(
            "ETHNOS_OLLAMA_VISION_VERIFIER_MODEL", "qwen3.5:9b"
        ),
        ollama_vision_num_predict=int(
            os.getenv("ETHNOS_OLLAMA_VISION_NUM_PREDICT", "256")
        ),
        ollama_math_model=os.getenv("ETHNOS_OLLAMA_MATH_MODEL", "qwen3.5:4b"),
        question_image_cache_dir=Path(
            os.getenv(
                "ETHNOS_QUESTION_IMAGE_CACHE_DIR",
                PROJECT_ROOT / "data" / "cache" / "question_images",
            )
        ),
        question_capture_dir=Path(
            os.getenv(
                "ETHNOS_QUESTION_CAPTURE_DIR",
                PROJECT_ROOT / "data" / "runs" / "captures",
            )
        ),
        agent_model=os.getenv("ETHNOS_AGENT_MODEL"),
        agent_model_profile=os.getenv("ETHNOS_AGENT_MODEL_PROFILE", "cpu-local"),
        agent_allow_web=_parse_bool(os.getenv("ETHNOS_AGENT_ALLOW_WEB"), default=False),
        agent_vision_pages=os.getenv("ETHNOS_AGENT_VISION_PAGES", "auto"),
        prompt_path=prompt_path,
    )


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError("Boolean environment values must be one of true/false")
