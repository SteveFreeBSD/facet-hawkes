"""The deliberately narrow Hawkes-to-Facet SSH proof bridge."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from ethnos.hawkes_host import FACET_SSH_COMMAND, _call_facet, _facet_prompt, handle
from ethnos.hawkes_protocol import AnswerPayload, SolveRequest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = PROJECT_ROOT / "deploy" / "facet" / "ethnos_facet_hawkes.py"
MATHML = "<math><msup><mi>x</mi><mn>2</mn></msup></math>"


def _request(*, engine="facet", mathml=None, instruction="Simplify x squared."):
    return {
        "protocol_version": 1,
        "operation": "solve_hawkes_problem",
        "request_id": "facet-poc",
        "origin": "https://learn.hawkeslearning.com",
        "solve_engine": engine,
        "problem": {
            "prompt_text": instruction,
            "mathml": [MATHML] if mathml is None else mathml,
        },
    }


def _facet_result(**changes):
    result = {
        "text": "FINAL ANSWER: x^2",
        "requested_backend": "gpu",
        "actual_backend": "gpu",
        "runtime": "Ollama 0.33.2",
        "model": "qwen3:0.6b",
        "device": "AMD Radeon 890M Graphics (RADV STRIX1)",
        "elapsed_ms": 812.5,
        "fallback": False,
    }
    result.update(changes)
    return result


def test_protocol_accepts_only_engine_not_execution_configuration():
    assert SolveRequest.model_validate(_request()).solve_engine == "facet"
    assert (
        SolveRequest.model_validate(_request(engine="ethnos")).solve_engine == "ethnos"
    )
    with pytest.raises(ValueError):
        SolveRequest.model_validate({**_request(), "solve_engine": "garbage"})


@pytest.mark.parametrize(
    "field",
    [
        "ssh_host",
        "username",
        "executable",
        "backend",
        "remote_command",
        "model",
        "path",
    ],
)
def test_protocol_rejects_browser_execution_fields(field):
    with pytest.raises(ValueError):
        SolveRequest.model_validate({**_request(), field: "browser-controlled"})


def test_default_request_still_uses_the_existing_ethnos_path(monkeypatch):
    request = _request(engine="ethnos")
    request.pop("solve_engine")
    monkeypatch.setattr(
        "ethnos.hawkes_host._solve_from_markup",
        lambda *_args: (AnswerPayload(display_text="x^2", keyboard_entry="x^2"), ""),
    )
    monkeypatch.setattr(
        "ethnos.hawkes_host._call_facet",
        lambda *_args: pytest.fail("default Ethnos request reached Facet"),
    )

    response = handle(request)

    assert response.status == "ready"
    assert response.answer.display_text == "x^2"
    assert response.certainty.source == "markup"


def test_facet_requires_readable_mathml_and_does_not_fall_back(monkeypatch):
    monkeypatch.setattr(
        "ethnos.hawkes_host._call_facet",
        lambda *_args: pytest.fail("Facet was called without MathML"),
    )
    request = _request(mathml=[])
    request["problem"]["screenshot_png_base64"] = "not-used"

    response = handle(request)

    assert response.status == "unsupported"
    assert response.answer is None
    assert "requires readable Hawkes MathML" in response.message


def test_prompt_is_stdin_data_and_ssh_argv_is_fixed(monkeypatch):
    instruction = "Simplify $(touch /tmp/never) ; `id` && echo nope."
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, 0, json.dumps(_facet_result()), "")

    monkeypatch.setattr("ethnos.hawkes_host.subprocess.run", fake_run)
    result = _call_facet(f"Instruction: {instruction}")

    assert result["actual_backend"] == "gpu"
    assert tuple(seen["argv"]) == FACET_SSH_COMMAND
    assert instruction not in " ".join(seen["argv"])
    assert instruction in json.loads(seen["kwargs"]["input"])["prompt"]
    assert seen["kwargs"]["shell"] is False


def test_fixed_prompt_does_not_teach_the_model_to_emit_placeholder_tags():
    prompt = _facet_prompt("Simplify.", ["x^2"])

    assert "FINAL ANSWER:" in prompt
    assert "<answer>" not in prompt
    assert "Do not repeat the input expression or output an equals sign" in prompt


def test_valid_gpu_json_becomes_a_normal_solve_response(monkeypatch):
    monkeypatch.setattr(
        "ethnos.hawkes_host._call_facet", lambda _prompt: _facet_result()
    )

    response = handle(_request())

    assert response.status == "ready"
    assert response.answer.display_text == "x^2"
    assert response.answer.keyboard_entry == "x^2"
    assert response.certainty.source == "Facet · GPU · casbox"
    assert response.certainty.model == "qwen3:0.6b"
    assert response.certainty.runtime == "Ollama 0.33.2"
    assert "Radeon 890M" in response.certainty.device
    assert response.certainty.elapsed_ms == 812.5
    assert response.certainty.insertable is True


@pytest.mark.parametrize(
    ("completed", "message"),
    [
        (subprocess.CompletedProcess([], 0, "not json", ""), "malformed JSON"),
        (
            subprocess.CompletedProcess(
                [], 0, json.dumps(_facet_result(actual_backend="cpu")), ""
            ),
            "required GPU backend",
        ),
        (subprocess.CompletedProcess([], 255, "", "connection refused"), "status 255"),
    ],
)
def test_malformed_wrong_backend_and_ssh_failure_fail_closed(
    monkeypatch, completed, message
):
    monkeypatch.setattr(
        "ethnos.hawkes_host.subprocess.run", lambda *_args, **_kwargs: completed
    )

    response = handle(_request())

    assert response.status == "error"
    assert response.answer is None
    assert message in response.message


def test_facet_contract_rejects_missing_fallback(monkeypatch):
    result = _facet_result()
    result.pop("fallback")
    monkeypatch.setattr(
        "ethnos.hawkes_host.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 0, json.dumps(result), ""
        ),
    )

    response = handle(_request())

    assert response.status == "error"
    assert response.answer is None
    assert "runtime result contract" in response.message


def _load_helper():
    spec = importlib.util.spec_from_file_location("ethnos_facet_hawkes", HELPER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_remote_helper_accepts_only_its_fixed_prompt_operation():
    helper = _load_helper()
    good = json.dumps(
        {
            "protocol_version": 1,
            "operation": helper.EXPECTED_OPERATION,
            "prompt": "fixed prompt",
        }
    ).encode()
    assert helper._parse_request(good) == "fixed prompt"

    for extra in ("backend", "model", "path", "executable", "ssh_host"):
        payload = json.loads(good)
        payload[extra] = "not allowed"
        with pytest.raises(ValueError, match="exactly"):
            helper._parse_request(json.dumps(payload).encode())


def test_remote_helper_invokes_facet_as_argv_without_a_shell(monkeypatch, capsys):
    helper = _load_helper()
    seen = {}
    monkeypatch.setattr(helper, "_read_request", lambda: "literal ; $(untrusted)")
    monkeypatch.setattr(helper.Path, "is_file", lambda _path: True)

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, 0, json.dumps(_facet_result()), "")

    monkeypatch.setattr(helper.subprocess, "run", fake_run)

    assert helper.main() == 0
    assert seen["argv"] == [
        helper.FACET_EXECUTABLE,
        "run",
        "literal ; $(untrusted)",
        "--backend",
        "gpu",
    ]
    assert seen["kwargs"]["shell"] is False
    assert json.loads(capsys.readouterr().out)["actual_backend"] == "gpu"


def test_remote_helper_fails_closed_when_facet_is_missing(monkeypatch, capsys):
    helper = _load_helper()
    monkeypatch.setattr(helper, "_read_request", lambda: "fixed prompt")
    monkeypatch.setattr(helper.Path, "is_file", lambda _path: False)
    monkeypatch.setattr(
        helper.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("missing Facet executable was invoked"),
    )

    assert helper.main() == 1
    assert "Facet executable is missing" in capsys.readouterr().err
