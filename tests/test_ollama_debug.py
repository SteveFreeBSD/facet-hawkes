from __future__ import annotations

from argparse import Namespace

from ethnos.cli import (
    _print_ollama_debug,
    answer_num_predict,
    build_parser,
    ollama_num_ctx,
    structure_num_predict,
)
from ethnos.config import load_settings
from ethnos.ollama_client import (
    OllamaDebugInfo,
    StructuredCallResult,
    _chat,
    _answer_chat_request_kwargs,
    _chat_request_kwargs,
    _repair_prompt,
    _response_summary,
)


def test_structure_parser_accepts_debug_ollama_flag():
    parser = build_parser()

    args = parser.parse_args(
        [
            "structure",
            "1",
            "--chunk-id",
            "80",
            "--num-predict",
            "4096",
            "--num-ctx",
            "32768",
            "--debug-ollama",
        ]
    )

    assert args.document_id == 1
    assert args.chunk_id == 80
    assert args.num_predict == 4096
    assert args.num_ctx == 32768
    assert args.debug_ollama is True


def test_response_summary_reports_compact_envelope_fields():
    response = {
        "done": True,
        "done_reason": "stop",
        "message": {"role": "assistant", "content": "{}", "thinking": "hidden thoughts"},
        "total_duration": 123,
        "eval_count": 17,
    }

    summary = _response_summary(response)

    assert summary["done"] is True
    assert summary["done_reason"] == "stop"
    assert summary["eval_count"] == 17
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
        num_predict=2048,
        num_ctx=8192,
        response_summary={
            "done": True,
            "done_reason": "length",
            "eval_count": 2048,
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
    assert "num_predict: 2048" in output
    assert "num_ctx: 8192" in output
    assert "done_reason: length" in output
    assert "eval_count: 2048" in output
    assert "message_content_length: 0" in output
    assert "total_duration: 456" in output


def test_structured_chat_request_sets_context_without_thinking():
    schema = {"type": "object", "properties": {"chunk_summary": {"type": "string"}}}

    kwargs = _chat_request_kwargs(
        "gemma-python", "prompt text", schema, num_predict=4096, num_ctx=8192
    )

    assert kwargs["model"] == "gemma-python"
    assert kwargs["messages"][0]["role"] == "system"
    assert kwargs["messages"][1] == {"role": "user", "content": "prompt text"}
    assert kwargs["format"] == schema
    assert kwargs["options"] == {"temperature": 0, "num_predict": 4096, "num_ctx": 8192}
    assert "think" not in kwargs
    assert "stream" not in kwargs


def test_answer_chat_request_uses_plain_text_and_context_without_thinking():
    kwargs = _answer_chat_request_kwargs(
        "gemma-python", "answer prompt", num_predict=1024, num_ctx=8192
    )

    assert kwargs["model"] == "gemma-python"
    assert kwargs["messages"][0]["role"] == "system"
    assert kwargs["messages"][1] == {"role": "user", "content": "answer prompt"}
    assert "format" not in kwargs
    assert kwargs["options"] == {"temperature": 0, "num_predict": 1024, "num_ctx": 8192}
    assert "think" not in kwargs
    assert "stream" not in kwargs


def test_num_predict_uses_cli_option_before_settings():
    settings = Namespace(ollama_structure_num_predict=2048)
    args = Namespace(num_predict=8192)

    assert structure_num_predict(args, settings) == 8192


def test_structure_num_predict_uses_environment_fallback(monkeypatch):
    monkeypatch.setenv("ETHNOS_OLLAMA_STRUCTURE_NUM_PREDICT", "3072")
    settings = load_settings()
    args = Namespace(num_predict=None)

    assert settings.ollama_structure_num_predict == 3072
    assert structure_num_predict(args, settings) == 3072


def test_answer_num_predict_uses_separate_environment_fallback(monkeypatch):
    monkeypatch.setenv("ETHNOS_OLLAMA_ANSWER_NUM_PREDICT", "1536")
    settings = load_settings()
    args = Namespace(num_predict=None)

    assert settings.ollama_answer_num_predict == 1536
    assert answer_num_predict(args, settings) == 1536


def test_default_ollama_budgets_and_context(monkeypatch):
    monkeypatch.delenv("ETHNOS_OLLAMA_NUM_PREDICT", raising=False)
    monkeypatch.delenv("ETHNOS_OLLAMA_STRUCTURE_NUM_PREDICT", raising=False)
    monkeypatch.delenv("ETHNOS_OLLAMA_ANSWER_NUM_PREDICT", raising=False)
    monkeypatch.delenv("ETHNOS_OLLAMA_NUM_CTX", raising=False)

    settings = load_settings()

    assert settings.ollama_structure_num_predict == 2048
    assert settings.ollama_answer_num_predict == 1536
    assert settings.ollama_num_ctx == 4096


def test_num_ctx_uses_cli_option_before_settings():
    settings = Namespace(ollama_num_ctx=8192)
    args = Namespace(num_ctx=32768)

    assert ollama_num_ctx(args, settings) == 32768


def test_num_ctx_uses_environment_fallback(monkeypatch):
    monkeypatch.setenv("ETHNOS_OLLAMA_NUM_CTX", "16384")
    settings = load_settings()
    args = Namespace(num_ctx=None)

    assert settings.ollama_num_ctx == 16384
    assert ollama_num_ctx(args, settings) == 16384


def test_done_reason_length_can_be_detected_for_warning():
    from ethnos.cli import _ollama_done_reason

    result = StructuredCallResult(
        raw_prompt="prompt",
        raw_response="{",
        result=None,
        parsed_json=None,
        validation_status="invalid_json",
        validation_error="Unterminated string",
        debug_info=OllamaDebugInfo(
            prompt_char_length=10,
            schema_top_level_keys=["type"],
            format_kind="json_schema",
            num_predict=2048,
            num_ctx=8192,
            response_summary={"done_reason": "length"},
        ),
    )

    assert _ollama_done_reason(result) == "length"


def test_chat_extracts_content_from_pydantic_response_shape():
    class FakeChatResponse:
        def model_dump(self, mode="json"):
            assert mode == "json"
            return {
                "done": True,
                "message": {"role": "assistant", "content": '{"chunk_summary": null}'},
            }

    class FakeClient:
        def chat(self, **kwargs):
            self.kwargs = kwargs
            return FakeChatResponse()

    client = FakeClient()
    result = _chat(
        client=client,
        prompt="prompt text",
        schema={"type": "object"},
        model_name="gemma-python",
        num_predict=2048,
        num_ctx=8192,
    )

    assert result.content == '{"chunk_summary": null}'
    assert result.response_summary["done"] is True
    assert client.kwargs["options"]["num_ctx"] == 8192


def test_repair_prompt_keeps_json_instruction_at_end():
    prompt = "Chunk text:\nimportant material"

    repaired = _repair_prompt(prompt)

    assert repaired.startswith(prompt)
    assert repaired.endswith("No Markdown fences, no commentary.")
