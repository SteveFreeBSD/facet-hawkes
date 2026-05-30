from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_topic_extraction_prompt_keeps_gemma_critical_constraints():
    prompt = (PROJECT_ROOT / "prompts" / "topic_extraction.md").read_text(
        encoding="utf-8"
    )

    assert "Return only schema-valid JSON" in prompt
    assert "extra keys" in prompt
    assert "topics: at least 1 main subject for study chunks" in prompt
    assert "every example object has title and body" in prompt
    assert "Do not use [] for topics on study chunks." in prompt


def test_mc_answer_prompt_requires_context_grounded_json_selection():
    prompt = (PROJECT_ROOT / "prompts" / "mc_answer.md").read_text(encoding="utf-8")

    assert "using only the provided local PDF context" in prompt
    assert "Question type:" in prompt
    assert "Return only JSON" in prompt
    assert '"selected_option"' in prompt
    assert "If question type is true_false" in prompt
    assert "True/False option label" in prompt
    assert "target term" in prompt.lower()
    assert "first locate that exact target" in prompt
    assert "apply that theory's stated rule" in prompt
    assert "ordinary moral judgment" in prompt
    assert "related variant" in prompt
    assert "different named theory" in prompt
    assert "{option_labels}" in prompt
