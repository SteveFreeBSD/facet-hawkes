from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_mc_answer_prompt_requires_context_grounded_json_selection():
    prompt = (PROJECT_ROOT / "prompts" / "mc_answer.md").read_text(encoding="utf-8")

    assert "using only the provided local PDF context" in prompt
    assert "Return only JSON" in prompt
    assert '"selected_option"' in prompt
    assert "target term" in prompt.lower()
    assert "first locate that exact target term" in prompt
    assert "related variant" in prompt
    assert "different named theory" in prompt
    assert "A, B, C, or D" in prompt
