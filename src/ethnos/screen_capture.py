"""Safe, user-selected screen capture for image-question workflows."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess


def capture_question_region(
    output_dir: Path,
    *,
    captured_at: datetime | None = None,
) -> Path:
    """Open Spectacle's region selector and return the captured PNG path."""
    spectacle = shutil.which("spectacle")
    if spectacle is None:
        raise RuntimeError(
            "--capture-question requires KDE Spectacle. Install Spectacle or use "
            "--question-image with an existing PNG, JPG, or WebP file."
        )

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = captured_at or datetime.now(timezone.utc)
    base_name = f"question-{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}"
    image_path = _unused_path(output_dir, base_name)
    result = subprocess.run(
        [
            spectacle,
            "--region",
            "--background",
            "--nonotify",
            f"--output={image_path}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"Question capture failed or was cancelled{suffix}")
    if not image_path.is_file() or image_path.stat().st_size == 0:
        raise RuntimeError("Question capture was cancelled; no image was saved.")
    return image_path


def default_capture_answer_path(image_path: Path) -> Path:
    return image_path.with_name(f"{image_path.stem}-answer.png")


def default_capture_trace_dir(image_path: Path) -> Path:
    return image_path.with_name(f"{image_path.stem}-trace")


def open_answer_image(image_path: Path) -> bool:
    """Open an answer PNG in the desktop's configured viewer when available."""
    opener = shutil.which("xdg-open")
    if opener is None:
        return False
    subprocess.Popen(
        [opener, str(image_path.expanduser().resolve())],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return True


def _unused_path(output_dir: Path, base_name: str) -> Path:
    candidate = output_dir / f"{base_name}.png"
    sequence = 2
    while candidate.exists():
        candidate = output_dir / f"{base_name}-{sequence}.png"
        sequence += 1
    return candidate
