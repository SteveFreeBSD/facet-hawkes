"""Prompt-template loading with file-change invalidation."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path


def read_prompt_template(prompt_path: Path) -> str:
    resolved = prompt_path.resolve()
    stat = resolved.stat()
    return _read_prompt_template(str(resolved), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=32)
def _read_prompt_template(path: str, _mtime_ns: int, _size: int) -> str:
    return Path(path).read_text(encoding="utf-8")
