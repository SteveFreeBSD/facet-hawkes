import json

import pytest

from ethnos.question_image import (
    QuestionImageTranscription,
    answer_question_image,
    build_solver_question,
    transcribe_question_image,
)


class FakeVisionClient:
    def __init__(self, *contents):
        self.contents = list(contents)
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "message": {"content": json.dumps(self.contents.pop(0))},
            "done_reason": "stop",
        }


def test_transcribe_question_image_preserves_math_and_diagram_details(tmp_path):
    image_path = tmp_path / "problem.png"
    image_path.write_bytes(b"not-decoded-by-fake-client")
    transcription = {
        "problem_text": "Solve x² - 5x + 6 = 0.",
        "expressions": ["x² - 5x + 6 = 0"],
        "answer_choices": ["A. x = 2", "B. x = 3"],
        "diagram_description": "A coordinate plane with closed points.",
        "uncertainties": [],
    }
    client = FakeVisionClient(transcription, transcription)

    result = transcribe_question_image(
        image_path=image_path,
        instruction="Solve the attached question.",
        model_name="vision-model",
        client=client,
        num_predict=512,
        num_ctx=4096,
    )

    assert result.transcription.problem_text == "Solve x² - 5x + 6 = 0."
    assert result.verification_issues == []
    assert len(client.calls) == 2
    assert client.calls[0]["model"] == "vision-model"
    assert result.verifier_model == "vision-model"
    assert client.calls[0]["messages"][0]["images"] == [str(image_path.resolve())]
    assert "Do not solve the problem" in client.calls[0]["messages"][0]["content"]
    assert "Independently re-read" in client.calls[1]["messages"][0]["content"]


def test_transcribe_question_image_supports_independent_verifier(tmp_path):
    image_path = tmp_path / "problem.png"
    image_path.write_bytes(b"image")
    transcription = {
        "problem_text": "Expand (x + 8)^2.",
        "expressions": ["(x + 8)^2"],
        "answer_choices": [],
        "diagram_description": "",
        "uncertainties": [],
    }
    client = FakeVisionClient(transcription, transcription)

    result = transcribe_question_image(
        image_path=image_path,
        instruction="Solve.",
        model_name="ocr-model",
        verifier_model_name="verifier-model",
        client=client,
        num_predict=256,
        num_ctx=4096,
    )

    assert result.vision_model == "ocr-model"
    assert result.verifier_model == "verifier-model"
    assert [call["model"] for call in client.calls] == [
        "ocr-model",
        "verifier-model",
    ]


def test_transcription_cache_skips_both_model_calls(tmp_path):
    image_path = tmp_path / "problem.png"
    image_path.write_bytes(b"same-image-content")
    transcription = {
        "problem_text": "Expand (x + 8)^2.",
        "expressions": ["(x + 8)^2"],
        "answer_choices": [],
        "diagram_description": "",
        "uncertainties": [],
    }
    first_client = FakeVisionClient(transcription, transcription)

    first = transcribe_question_image(
        image_path=image_path,
        instruction="Solve.",
        model_name="ocr-model",
        verifier_model_name="verifier-model",
        client=first_client,
        num_predict=256,
        num_ctx=4096,
        cache_dir=tmp_path / "cache",
    )
    second_client = FakeVisionClient()
    second = transcribe_question_image(
        image_path=image_path,
        instruction="Solve.",
        model_name="ocr-model",
        verifier_model_name="verifier-model",
        client=second_client,
        num_predict=256,
        num_ctx=4096,
        cache_dir=tmp_path / "cache",
    )

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.transcription == first.transcription
    assert second_client.calls == []


def test_transcribe_question_image_flags_expression_disagreement(tmp_path):
    image_path = tmp_path / "problem.png"
    image_path.write_bytes(b"image")
    initial = {
        "problem_text": "Solve the expression.",
        "expressions": ["x = (5 * 1)/2"],
        "answer_choices": [],
        "diagram_description": "",
        "uncertainties": [],
    }
    verified = {
        "problem_text": "Solve the expression.",
        "expressions": [r"x = \frac{5 \pm \sqrt{1}}{2}"],
        "answer_choices": [],
        "diagram_description": "",
        "uncertainties": [],
    }

    result = transcribe_question_image(
        image_path=image_path,
        instruction="Solve.",
        model_name="vision-model",
        client=FakeVisionClient(initial, verified),
        num_predict=512,
        num_ctx=4096,
    )

    assert result.verification_issues == [
        "The two vision passes disagreed about mathematical expressions."
    ]


def test_transcription_allows_whole_expression_versus_term_list(tmp_path):
    image_path = tmp_path / "problem.png"
    image_path.write_bytes(b"image")
    initial = {
        "problem_text": "Factor the trinomial.\n-10xy² - 15xy + 25x",
        "expressions": ["-10xy² - 15xy + 25x"],
        "answer_choices": [],
        "diagram_description": "",
        "uncertainties": [],
    }
    verified = {
        "problem_text": "Factor the trinomial.\n-10xy^2 - 15xy + 25x",
        "expressions": ["-10xy^2", "-15xy", "25x"],
        "answer_choices": [],
        "diagram_description": "",
        "uncertainties": [],
    }

    result = transcribe_question_image(
        image_path=image_path,
        instruction="Solve.",
        model_name="vision-model",
        client=FakeVisionClient(initial, verified),
        num_predict=512,
        num_ctx=4096,
    )

    assert result.verification_issues == []


def test_transcription_discards_scoreboard_metadata_as_answer_choices(tmp_path):
    image_path = tmp_path / "problem.png"
    image_path.write_bytes(b"image")
    clean = {
        "problem_text": "Expand (x + 8)^2.",
        "expressions": ["(x + 8)^2"],
        "answer_choices": [],
        "diagram_description": "",
        "uncertainties": [],
    }
    noisy = {
        **clean,
        "answer_choices": ["6/16", "Correct", "12", "Incorrect"],
    }

    result = transcribe_question_image(
        image_path=image_path,
        instruction="Solve.",
        model_name="vision-model",
        client=FakeVisionClient(noisy, clean),
        num_predict=512,
        num_ctx=4096,
    )

    assert result.transcription.answer_choices == []
    assert result.initial_transcription.answer_choices == []
    assert result.verification_issues == []


def test_transcription_reconciles_ui_metadata_across_passes(tmp_path):
    image_path = tmp_path / "problem.png"
    image_path.write_bytes(b"image")
    initial = {
        "problem_text": "Expand (x + 8)^2.",
        "expressions": ["(x + 8)^2"],
        "answer_choices": ["12"],
        "interface_metadata": [],
        "diagram_description": "",
        "uncertainties": [],
    }
    verified = {
        **initial,
        "answer_choices": [],
        "interface_metadata": ["Question 11 of 14", "12", "Incorrect"],
    }

    result = transcribe_question_image(
        image_path=image_path,
        instruction="Solve.",
        model_name="vision-model",
        client=FakeVisionClient(initial, verified),
        num_predict=512,
        num_ctx=4096,
    )

    assert result.initial_transcription.answer_choices == []
    assert result.transcription.answer_choices == []
    assert result.verification_issues == []


def test_build_solver_question_retains_choices_diagram_and_uncertainties():
    transcription = QuestionImageTranscription(
        problem_text="Choose the matching graph.",
        expressions=["y = |x|"],
        answer_choices=["A. Graph I", "B. Graph II"],
        diagram_description="Graph I has an open endpoint at (0, 0).",
        uncertainties=["The label on Graph II may be 2 or 3."],
    )

    question = build_solver_question("Answer the image.", transcription)

    assert "y = |x|" in question
    assert "A. Graph I" in question
    assert "open endpoint at (0, 0)" in question
    assert "do not silently assume" in question
    assert "may be 2 or 3" in question
    assert "FINAL ANSWER:" in question
    assert "KEYBOARD ENTRY:" in question
    assert "* for explicit multiplication" in question


def test_answer_question_image_uses_compact_structured_solve():
    client = FakeVisionClient(
        {
            "work": "Use (a+b)^2 = a^2 + 2ab + b^2.",
            "verification": "Expanding the factors gives the same polynomial.",
            "final_answer": "x^2 + 16x + 64",
        }
    )
    rows = [
        {
            "id": 1,
            "source_citation": "precalc.pdf p. 1, chunk 1",
            "section_label": "chapter_content",
            "content_role": "core",
            "text": "The square of a binomial follows (a+b)^2.",
        }
    ]

    result = answer_question_image(
        question="Expand (x+8)^2.",
        context_rows=rows,
        max_chars=1200,
        model_name="math-model",
        client=client,
        num_predict=2048,
        num_ctx=4096,
    )

    assert result.raw_response.endswith("FINAL ANSWER: x^2 + 16x + 64")
    assert result.debug_info is not None
    assert result.debug_info.format_kind == "json_schema"
    assert result.debug_info.num_predict == 384
    assert client.calls[0]["options"]["num_predict"] == 384


def test_transcribe_question_image_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        transcribe_question_image(
            image_path=tmp_path / "missing.png",
            instruction="Solve",
            model_name="vision-model",
            client=FakeVisionClient({}),
            num_predict=512,
            num_ctx=4096,
        )


def test_transcribe_question_image_rejects_unsupported_suffix(tmp_path):
    image_path = tmp_path / "problem.pdf"
    image_path.write_bytes(b"pdf")

    with pytest.raises(ValueError, match="must use one of"):
        transcribe_question_image(
            image_path=image_path,
            instruction="Solve",
            model_name="vision-model",
            client=FakeVisionClient({}),
            num_predict=512,
            num_ctx=4096,
        )


def test_a_literal_newline_escape_does_not_read_as_disagreement():
    """Regression from a live question: 1/(6n^-5).

    Both readers transcribed the same expression, but one wrote the escape
    "\\n" as two literal characters before it. That defeated the line-based
    rescue, and a perfectly agreed reading was reported as a disagreement --
    which blocks insertion entirely.
    """
    from ethnos.question_image import QuestionImageTranscription, _verification_issues

    prose = "Simplify the following expression, writing your answer with only positive exponents."
    first = QuestionImageTranscription(
        problem_text=f"{prose}\n\\n\\frac{{1}}{{6n^{{-5}}}}", expressions=[]
    )
    second = QuestionImageTranscription(
        problem_text=f"{prose}\n\n\\frac{{1}}{{6n^{{-5}}}}",
        # The other reader decomposed the expression into single characters,
        # which is not a list of expressions.
        expressions=["1", "6", "n", "5"],
    )

    assert _verification_issues(first, second) == []


def test_a_real_disagreement_is_still_caught():
    from ethnos.question_image import QuestionImageTranscription, _verification_issues

    first = QuestionImageTranscription(
        problem_text="Simplify.\n\\frac{1}{6n^{-4}}", expressions=[r"\frac{1}{6n^{-4}}"]
    )
    second = QuestionImageTranscription(
        problem_text="Simplify.\n\\frac{1}{6n^{-5}}", expressions=[r"\frac{1}{6n^{-5}}"]
    )

    issues = _verification_issues(first, second)
    assert any("mathematical expressions" in issue for issue in issues)


def test_single_token_fragments_are_not_expressions():
    from ethnos.question_image import _structured_expressions

    assert _structured_expressions(["1", "6", "n", "5"]) == []
    assert _structured_expressions([r"\frac{1}{6n^{-5}}"]) != []
    assert _structured_expressions(["x^2", "y"]) == _structured_expressions(["x^2"])
