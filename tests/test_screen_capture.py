from datetime import datetime, timezone
from pathlib import Path
import subprocess

import pytest

from ethnos.cli import build_parser
from ethnos.screen_capture import (
    capture_question_region,
    default_capture_answer_path,
    default_capture_trace_dir,
    open_answer_image,
)


def test_capture_question_region_runs_spectacle_and_returns_png(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "ethnos.screen_capture.shutil.which", lambda _name: "/usr/bin/spectacle"
    )

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        output = next(item for item in command if item.startswith("--output="))
        Path(output.removeprefix("--output=")).write_bytes(b"PNG")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("ethnos.screen_capture.subprocess.run", fake_run)
    captured = capture_question_region(
        tmp_path / "captures",
        captured_at=datetime(2026, 9, 2, 15, 30, tzinfo=timezone.utc),
    )

    assert captured.name == "question-20260902T153000000000Z.png"
    assert captured.read_bytes() == b"PNG"
    assert calls[0][0] == [
        "/usr/bin/spectacle",
        "--region",
        "--background",
        "--nonotify",
        f"--output={captured}",
    ]
    assert calls[0][1] == {"check": False, "capture_output": True, "text": True}


def test_capture_question_region_refuses_missing_spectacle(tmp_path, monkeypatch):
    monkeypatch.setattr("ethnos.screen_capture.shutil.which", lambda _name: None)

    with pytest.raises(RuntimeError, match="requires KDE Spectacle"):
        capture_question_region(tmp_path)


def test_capture_question_region_detects_cancelled_capture(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ethnos.screen_capture.shutil.which", lambda _name: "/usr/bin/spectacle"
    )
    monkeypatch.setattr(
        "ethnos.screen_capture.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0),
    )

    with pytest.raises(RuntimeError, match="cancelled"):
        capture_question_region(tmp_path)


def test_capture_artifact_paths_stay_next_to_question_image(tmp_path):
    question = tmp_path / "question-1.png"

    assert default_capture_answer_path(question) == tmp_path / "question-1-answer.png"
    assert default_capture_trace_dir(question) == tmp_path / "question-1-trace"


def test_open_answer_image_uses_desktop_opener(tmp_path, monkeypatch):
    answer = tmp_path / "answer.png"
    calls = []
    monkeypatch.setattr(
        "ethnos.screen_capture.shutil.which", lambda _name: "/usr/bin/xdg-open"
    )
    monkeypatch.setattr(
        "ethnos.screen_capture.subprocess.Popen",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )

    assert open_answer_image(answer) is True
    assert calls[0][0] == ["/usr/bin/xdg-open", str(answer.resolve())]
    assert calls[0][1]["start_new_session"] is True


def test_ask_parser_accepts_capture_question_and_rejects_two_image_sources():
    parser = build_parser()
    args = parser.parse_args(["ask", "3", "Solve it", "--capture-question"])

    assert args.capture_question is True
    assert args.question_image is None

    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "ask",
                "3",
                "Solve it",
                "--capture-question",
                "--question-image",
                "problem.png",
            ]
        )
