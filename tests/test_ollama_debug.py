from __future__ import annotations

from ethnos.cli import _print_ollama_debug, build_parser
from ethnos.ollama_client import OllamaDebugInfo, _response_summary


def test_structure_parser_accepts_debug_ollama_flag():
    parser = build_parser()

    args = parser.parse_args(["structure", "1", "--chunk-id", "80", "--debug-ollama"])

    assert args.document_id == 1
    assert args.chunk_id == 80
    assert args.debug_ollama is True


def test_response_summary_reports_compact_envelope_fields():
    response = {
        "done": True,
        "done_reason": "stop",
        "message": {"role": "assistant", "content": "{}", "thinking": "hidden thoughts"},
        "total_duration": 123,
    }

    summary = _response_summary(response)

    assert summary["done"] is True
    assert summary["done_reason"] == "stop"
    assert summary["message_content_length"] == 2
    assert summary["message_thinking_exists"] is True
    assert summary["error"] is None
    assert summary["total_duration"] == 123
    assert "message" in summary["top_level_keys"]


def test_print_ollama_debug_outputs_request_and_response_summary(capsys):
    debug_info = OllamaDebugInfo(
        prompt_char_length=321,
        schema_top_level_keys=["properties", "required", "title", "type"],
        format_kind="json_schema",
        response_summary={
            "done": True,
            "done_reason": "stop",
            "message_content_length": 0,
            "message_thinking_exists": False,
            "error": None,
            "total_duration": 456,
            "top_level_keys": ["done", "message", "total_duration"],
        },
    )

    _print_ollama_debug(80, debug_info)
    output = capsys.readouterr().out

    assert "Ollama debug for chunk 80:" in output
    assert "prompt chars: 321" in output
    assert "schema top-level keys: properties, required, title, type" in output
    assert "format: json_schema" in output
    assert "message_content_length: 0" in output
    assert "total_duration: 456" in output

