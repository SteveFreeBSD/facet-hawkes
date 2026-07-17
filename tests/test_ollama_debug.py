from __future__ import annotations

import json
from argparse import Namespace

from ethnos.cli import (
    _print_ollama_debug,
    answer_num_predict,
    build_parser,
    main,
    ollama_num_ctx,
    structure_num_predict,
)
from ethnos.cli.commands import inspect as inspect_commands
from ethnos.config import load_settings, parse_ollama_think
from ethnos.ollama_client import (
    MCAnswerResult,
    OllamaDebugInfo,
    StructuredCallResult,
    answer_mc_question,
    extract_chunk,
    structured_chat_json,
    _chat,
    _answer_chat_request_kwargs,
    _chat_request_kwargs,
    _extraction_schema,
    _mc_chat_request_kwargs,
    _ollama_options,
    _ollama_schema,
    _repair_prompt,
    _retry_delay_seconds,
    _response_summary,
    _validate_choice_response,
    _validate_essay_response,
    _validate_mc_response,
)
from ethnos.prompt_cache import read_prompt_template
from ethnos.models import ChunkRecord, ExtractionResult


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
            "--all-roles",
            "--debug-ollama",
        ]
    )

    assert args.document_id == 1
    assert args.chunk_id == 80
    assert args.num_predict == 4096
    assert args.num_ctx == 32768
    assert args.all_roles is True
    assert args.debug_ollama is True


def test_mc_bench_parser_uses_measured_short_context_default():
    parser = build_parser()

    args = parser.parse_args(
        [
            "mc-bench",
            "1",
            "--quiz",
            "data/runs/perf-quiz-medium-20.json",
        ]
    )

    assert args.chars == 300


def test_cli_handles_unexpected_keyboard_interrupt(monkeypatch, capsys):
    def interrupted(_args):
        raise KeyboardInterrupt

    monkeypatch.setattr(inspect_commands, "documents_cmd", interrupted)

    assert main(["documents"]) == 130
    assert "Interrupted." in capsys.readouterr().err


def test_response_summary_reports_compact_envelope_fields():
    response = {
        "done": True,
        "done_reason": "stop",
        "message": {
            "role": "assistant",
            "content": "{}",
            "thinking": "hidden thoughts",
        },
        "total_duration": 123,
        "eval_count": 17,
    }

    summary = _response_summary(response)

    assert summary["done"] is True
    assert summary["done_reason"] == "stop"
    assert summary["eval_count"] == 17
    assert summary["message_content_length"] == 2
    assert summary["message_thinking_length"] == 15
    assert summary["message_thinking_exists"] is True
    assert summary["error"] is None
    assert summary["total_duration"] == 123
    assert "message" in summary["top_level_keys"]


def test_response_summary_ignores_empty_thinking_field():
    response = {
        "message": {"role": "assistant", "content": "{}", "thinking": ""},
    }

    summary = _response_summary(response)

    assert summary["message_thinking_length"] == 0
    assert summary["message_thinking_exists"] is False


def test_extract_chunk_uses_exponential_backoff_between_retries(tmp_path):
    class InvalidJsonClient:
        def chat(self, **kwargs):
            return {"message": {"content": "not json"}, "done_reason": "stop"}

    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("{source_citation}\n{chunk_text}", encoding="utf-8")
    chunk = ChunkRecord(
        document_id=1,
        page_start=1,
        page_end=1,
        chunk_index=1,
        text="Virtue ethics emphasizes character.",
        char_count=35,
        source_citation="ethics.pdf p. 1, chunk 1",
    )
    sleeps = []

    result = extract_chunk(
        chunk,
        prompt_path,
        model_name="test-model",
        host="http://localhost:11434",
        timeout=1,
        num_predict=128,
        num_ctx=2048,
        retries=2,
        client=InvalidJsonClient(),
        retry_sleep=sleeps.append,
    )

    assert result.validation_status == "invalid_json"
    assert sleeps == [0.5, 1.0]
    assert _retry_delay_seconds(4) == 4.0


def test_prompt_template_cache_invalidates_when_file_changes(tmp_path):
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("First {value}", encoding="utf-8")

    first = read_prompt_template(prompt_path)
    prompt_path.write_text("Second {value}", encoding="utf-8")
    second = read_prompt_template(prompt_path)

    assert first == "First {value}"
    assert second == "Second {value}"


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
            "message_thinking_length": 0,
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
    assert kwargs["think"] is False
    assert "stream" not in kwargs


def test_generic_structured_chat_accepts_schema_messages_and_images():
    class FakeClient:
        def chat(self, **kwargs):
            self.kwargs = kwargs
            return {
                "message": {"content": '{"ok": true}'},
                "done_reason": "stop",
            }

    client = FakeClient()

    result = structured_chat_json(
        client=client,
        model_name="gemma3:4b",
        messages=[{"role": "user", "content": "describe"}],
        schema={
            "type": "object",
            "properties": {"ok": {"type": "boolean", "default": False}},
            "required": ["ok"],
        },
        num_predict=64,
        num_ctx=4096,
        images=["page.png"],
    )

    assert result.validation_status == "valid"
    assert result.parsed_json == {"ok": True}
    assert client.kwargs["model"] == "gemma3:4b"
    assert client.kwargs["messages"][0]["images"] == ["page.png"]
    assert "default" not in json.dumps(client.kwargs["format"])


def test_ollama_schema_strips_schema_defaults_but_keeps_titles():
    schema = {
        "title": "ExtractionResult",
        "type": "object",
        "properties": {
            "chunk_summary": {
                "title": "Chunk Summary",
                "default": "",
                "type": "string",
            },
            "topics": {
                "type": "array",
                "items": {
                    "title": "TopicExtraction",
                    "type": "object",
                    "properties": {"name": {"title": "Name", "type": "string"}},
                },
            },
        },
        "required": ["chunk_summary", "topics"],
    }

    compact = _ollama_schema(schema)

    assert compact == {
        "title": "ExtractionResult",
        "type": "object",
        "properties": {
            "chunk_summary": {"title": "Chunk Summary", "type": "string"},
            "topics": {
                "type": "array",
                "items": {
                    "title": "TopicExtraction",
                    "type": "object",
                    "properties": {"name": {"title": "Name", "type": "string"}},
                },
            },
        },
        "required": ["chunk_summary", "topics"],
    }


def test_ollama_schema_compacts_real_extraction_schema_safely():
    compact = _ollama_schema(ExtractionResult.model_json_schema())
    serialized = json.dumps(compact)

    assert '"default"' not in serialized
    assert compact["title"] == "ExtractionResult"
    assert compact["required"] == [
        "chunk_summary",
        "topics",
        "key_terms",
        "examples",
        "questions",
    ]
    assert compact["$defs"]["Example"]["required"] == ["title", "body"]
    assert compact["$defs"]["TopicExtraction"]["required"] == [
        "name",
        "summary",
        "confidence",
    ]


def test_extraction_schema_is_cached():
    assert _extraction_schema() is _extraction_schema()


def test_answer_chat_request_uses_plain_text_and_context_without_thinking():
    kwargs = _answer_chat_request_kwargs(
        "gemma-python", "answer prompt", num_predict=1024, num_ctx=8192
    )

    assert kwargs["model"] == "gemma-python"
    assert kwargs["messages"][0]["role"] == "system"
    assert kwargs["messages"][1] == {"role": "user", "content": "answer prompt"}
    assert "format" not in kwargs
    assert kwargs["options"] == {"temperature": 0, "num_predict": 1024, "num_ctx": 8192}
    assert kwargs["think"] is False
    assert "stream" not in kwargs


def test_mc_chat_request_uses_json_schema_and_defaults_think_false():
    schema = {"type": "object", "properties": {"selected_option": {"enum": ["A", "B"]}}}

    kwargs = _mc_chat_request_kwargs(
        "gemma-python", "mc prompt", schema, num_predict=32, num_ctx=8192
    )

    assert kwargs["model"] == "gemma-python"
    assert kwargs["messages"][0]["role"] == "system"
    assert "multiple-choice" in kwargs["messages"][0]["content"]
    assert kwargs["messages"][1] == {"role": "user", "content": "mc prompt"}
    assert kwargs["format"] == schema
    assert kwargs["options"] == {"temperature": 0, "num_predict": 32, "num_ctx": 8192}
    assert kwargs["think"] is False
    assert "stream" not in kwargs


def test_mc_chat_request_can_omit_think():
    schema = {"type": "object", "properties": {"selected_option": {"enum": ["A", "B"]}}}

    kwargs = _mc_chat_request_kwargs(
        "gemma-python",
        "mc prompt",
        schema,
        num_predict=32,
        num_ctx=8192,
        think=None,
    )

    assert "think" not in kwargs


def test_ollama_options_can_include_env_thread_count(monkeypatch):
    monkeypatch.setenv("ETHNOS_OLLAMA_NUM_THREAD", "4")

    assert _ollama_options(num_predict=128, num_ctx=4096) == {
        "temperature": 0,
        "num_predict": 128,
        "num_ctx": 4096,
        "num_thread": 4,
    }


def test_ollama_options_rejects_invalid_env_thread_count(monkeypatch):
    monkeypatch.setenv("ETHNOS_OLLAMA_NUM_THREAD", "0")

    try:
        _ollama_options(num_predict=128, num_ctx=4096)
    except ValueError as exc:
        assert "ETHNOS_OLLAMA_NUM_THREAD must be a positive integer" in str(exc)
    else:
        raise AssertionError("Expected invalid ETHNOS_OLLAMA_NUM_THREAD to fail")


def test_validate_mc_response_accepts_valid_json():
    result = _validate_mc_response("prompt", '{"selected_option":"C"}')

    assert result == MCAnswerResult(
        raw_prompt="prompt",
        raw_response='{"selected_option":"C"}',
        selected_option="C",
        validation_status="valid",
        validation_error=None,
    )


def test_validate_mc_response_rejects_invalid_json_and_option():
    invalid_json = _validate_mc_response("prompt", "not json")
    invalid_option = _validate_mc_response("prompt", '{"selected_option":"E"}')
    empty = _validate_mc_response("prompt", "")
    invalid_for_true_false = _validate_mc_response(
        "prompt", '{"selected_option":"C"}', allowed_options=["A", "B"]
    )

    assert invalid_json.validation_status == "invalid_json"
    assert invalid_json.selected_option is None
    assert invalid_option.validation_status == "invalid_option"
    assert invalid_option.selected_option is None
    assert invalid_for_true_false.validation_status == "invalid_option"
    assert empty.validation_status == "empty_response"


def test_validate_choice_response_requires_schema_fields():
    valid = _validate_choice_response(
        "prompt",
        '{"selected_option":"A","evidence":"From context.","source_citations":["p. 1"]}',
        allowed_options=["A", "B"],
    )
    missing = _validate_choice_response(
        "prompt",
        '{"selected_option":"A"}',
        allowed_options=["A", "B"],
    )

    assert valid.validation_status == "valid"
    assert valid.selected_option == "A"
    assert missing.validation_status == "validation_error"
    assert "missing required field" in missing.validation_error


def test_validate_essay_response_requires_schema_fields():
    valid = _validate_essay_response(
        "prompt",
        json.dumps(
            {
                "answer": "Virtue ethics emphasizes character.",
                "key_points": ["Character"],
                "rubric": ["Mentions character"],
                "source_citations": ["p. 1"],
                "limitations": [],
            }
        ),
    )
    missing = _validate_essay_response("prompt", '{"answer":"Short answer"}')

    assert valid.validation_status == "valid"
    assert valid.answer == "Virtue ethics emphasizes character."
    assert missing.validation_status == "validation_error"
    assert "missing required field" in missing.validation_error


def test_answer_mc_question_uses_client_and_validates_response():
    class FakeClient:
        def chat(self, **kwargs):
            self.kwargs = kwargs
            return {"message": {"content": '{"selected_option":"B"}'}, "done": True}

    client = FakeClient()

    result = answer_mc_question(
        prompt="prompt",
        model_name="gemma-python",
        host="http://localhost:11434",
        timeout=30,
        num_predict=32,
        num_ctx=8192,
        allowed_options=["A", "B"],
        client=client,
    )

    assert result.selected_option == "B"
    assert result.validation_status == "valid"
    assert client.kwargs["think"] is False
    assert client.kwargs["format"]["properties"]["selected_option"]["enum"] == [
        "A",
        "B",
    ]
    assert client.kwargs["options"]["num_predict"] == 32
    assert result.debug_info.response_summary["done"] is True


def test_answer_mc_question_forwards_think_setting():
    class FakeClient:
        def chat(self, **kwargs):
            self.kwargs = kwargs
            return {"message": {"content": '{"selected_option":"A"}'}, "done": True}

    client = FakeClient()

    result = answer_mc_question(
        prompt="prompt",
        model_name="gemma-python",
        host="http://localhost:11434",
        timeout=30,
        num_predict=32,
        num_ctx=8192,
        allowed_options=["A", "B"],
        client=client,
        think="medium",
    )

    assert result.validation_status == "valid"
    assert client.kwargs["think"] == "medium"


def test_answer_mc_question_reports_request_failure():
    class FailingClient:
        def chat(self, **kwargs):
            raise RuntimeError("no model")

    result = answer_mc_question(
        prompt="prompt",
        model_name="gemma-python",
        host="http://localhost:11434",
        timeout=30,
        num_predict=32,
        num_ctx=8192,
        client=FailingClient(),
    )

    assert result.validation_status == "request_failed"
    assert result.selected_option is None
    assert "no model" in result.validation_error


def test_default_ollama_think_is_false(monkeypatch):
    monkeypatch.delenv("ETHNOS_OLLAMA_THINK", raising=False)
    settings = load_settings()
    assert settings.ollama_think is False


def test_ollama_think_can_be_enabled_via_env(monkeypatch):
    monkeypatch.setenv("ETHNOS_OLLAMA_THINK", "true")
    settings = load_settings()
    assert settings.ollama_think is True


def test_ollama_think_supports_auto_and_effort_values(monkeypatch):
    monkeypatch.setenv("ETHNOS_OLLAMA_THINK", "auto")
    assert load_settings().ollama_think is None
    assert parse_ollama_think("low") == "low"
    assert parse_ollama_think("medium") == "medium"
    assert parse_ollama_think("high") == "high"


def test_chat_request_kwargs_passes_think_true():
    schema = {"type": "object"}
    kwargs = _chat_request_kwargs(
        "gemma-python", "prompt", schema, num_predict=2048, num_ctx=8192, think=True
    )
    assert kwargs["think"] is True


def test_chat_request_kwargs_can_omit_think():
    schema = {"type": "object"}
    kwargs = _chat_request_kwargs(
        "gemma-python", "prompt", schema, num_predict=2048, num_ctx=8192, think=None
    )
    assert "think" not in kwargs


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

    assert settings.ollama_model == "gemma-python"
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
