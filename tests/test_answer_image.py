from pathlib import Path
import subprocess

import pytest

from ethnos.answer_image import (
    answer_card_answer_text,
    build_answer_card_text,
    build_key_command_text,
    extract_final_math,
    keyboard_entry_for_math,
    linearize_math,
    render_answer_image,
    symbol_commands_for,
    visual_math_answer,
)


def test_symbol_commands_match_only_symbols_used_in_answer():
    answer = r"x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}, \theta \le \pi"

    commands = symbol_commands_for(answer)

    assert [command.label for command in commands] == [
        "Fraction",
        "Square root",
        "Exponent",
        "Pi",
        "Theta",
        "Less than or equal",
        "Plus or minus",
    ]


def test_cube_root_renders_as_real_symbol_without_square_root_guidance():
    answer = r"FINAL ANSWER: 6\sqrt[3]{3}"

    assert linearize_math(answer) == "FINAL ANSWER: 6∛3"
    commands = symbol_commands_for(answer)
    assert [command.label for command in commands] == ["Cube root"]
    assert commands[0].symbol == "∛x"


def test_fraction_answer_renders_with_fraction_symbol_and_grouped_denominator():
    answer = r"FINAL ANSWER: \frac{1}{5yz^{7}}"

    assert linearize_math(answer) == "FINAL ANSWER: 1⁄(5yz⁷)"
    assert keyboard_entry_for_math(r"\frac{1}{5yz^{7}}") == "1/(5*y*z^7)"


def test_fraction_keyboard_entry_groups_an_additive_numerator():
    """A fraction bar covers the whole numerator, not only its last term."""
    assert keyboard_entry_for_math(r"\frac{26 - 29i}{37}") == "(26-29*i)/37"


def test_screenshot_fraction_answer_is_only_a_stacked_fraction():
    assert visual_math_answer(r"\frac{1}{5yz^7}") == "1\n────\n5yz⁷"


def test_renderer_repairs_model_output_missing_fraction_backslash():
    assert linearize_math(r"frac{1}{5yz^{7}}") == "1⁄(5yz⁷)"


def test_linearize_math_preserves_math_in_readable_form():
    answer = r"\(x = \frac{3}{4},\ y = \sqrt{9},\ z = x^{2},\ \theta \ge \pi\)"

    rendered = linearize_math(answer)

    assert rendered == "x = 3⁄4, y = √(9), z = x², θ ≥ π"


def test_key_command_text_has_keyboard_and_latex_forms():
    text = build_key_command_text(r"x = -b \pm \sqrt{d}")

    assert "Keyboard/homework entry: +/-" in text
    assert r"LaTeX: \pm" in text
    assert "Keyboard/homework entry: sqrt(x)" in text
    assert r"LaTeX: \sqrt{x}" in text


def test_symbol_commands_treat_ascii_star_and_cdot_as_multiplication():
    for answer in ("2*x", r"2 \cdot x", "2 · x"):
        labels = {command.label for command in symbol_commands_for(answer)}
        assert "Multiply" in labels


def test_extract_final_math_and_create_explicit_keyboard_entry():
    answer = (
        "Work: $-10xy^2 - 15xy + 25x$.\n"
        "The final answer is:\n"
        r"\[\boxed{5x(-y + 1)(2y + 5)}\]"
    )

    final_math = extract_final_math(answer)

    assert final_math == "5x(-y + 1)(2y + 5)"
    assert keyboard_entry_for_math(final_math) == "5*x*(-y+1)*(2*y+5)"
    assert answer_card_answer_text(answer) == (
        "FINAL ANSWER: 5x(-y + 1)(2y + 5)\n\nKEYBOARD ENTRY: 5*x*(-y+1)*(2*y+5)"
    )


def test_extract_final_math_supports_required_final_answer_line():
    answer = "Checked by expansion.\nFINAL ANSWER: x^2 - 1"

    assert extract_final_math(answer) == "x^2 - 1"


def test_answer_card_includes_question_answer_commands_and_sources():
    card = build_answer_card_text(
        question="Solve x^2 = 9",
        answer_text=r"x = \pm 3",
        sources=["precalc.pdf p. 42, chunk 18"],
    )

    assert "QUESTION\nSolve x² = 9" in card
    assert "ANSWER\nx = ± 3" in card
    assert "Plus or minus" in card
    assert "precalc.pdf p. 42, chunk 18" in card


def test_answer_card_can_omit_key_commands():
    card = build_answer_card_text(
        question="Factor the trinomial",
        answer_text=r"\boxed{5x(1-y)(2y+5)}",
        sources=["precalc.pdf p. 144"],
        include_key_commands=False,
    )

    assert card == "5x(1-y)(2y+5)"


def test_render_answer_image_writes_png_and_copyable_key_file(tmp_path, monkeypatch):
    image_path = tmp_path / "nested" / "answer.png"
    calls = []

    monkeypatch.setattr("ethnos.answer_image.shutil.which", lambda _name: "/pango")

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        output_arg = next(arg for arg in command if arg.startswith("--output="))
        Path(output_arg.removeprefix("--output=")).write_bytes(b"PNG")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("ethnos.answer_image.subprocess.run", fake_run)

    artifacts = render_answer_image(
        image_path=image_path,
        question="Solve x^2 = 9",
        answer_text=r"x = \pm 3",
        sources=["precalc.pdf p. 42, chunk 18"],
    )

    assert artifacts.image_path.read_bytes() == b"PNG"
    assert artifacts.keys_path is not None
    assert "Keyboard/homework entry: +/-" in artifacts.keys_path.read_text()
    assert calls[0][1] == {"check": True, "capture_output": True, "text": True}


def test_render_screenshot_answer_omits_key_command_file(tmp_path, monkeypatch):
    image_path = tmp_path / "answer.png"
    monkeypatch.setattr("ethnos.answer_image.shutil.which", lambda _name: "/pango")

    def fake_run(command, **kwargs):
        output_arg = next(arg for arg in command if arg.startswith("--output="))
        Path(output_arg.removeprefix("--output=")).write_bytes(b"PNG")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("ethnos.answer_image.subprocess.run", fake_run)

    artifacts = render_answer_image(
        image_path=image_path,
        question="Simplify (-4)^2",
        answer_text="FINAL ANSWER: 16",
        sources=[],
        include_key_commands=False,
    )

    assert artifacts.keys_path is None
    assert not image_path.with_suffix(".keys.txt").exists()


def test_render_answer_image_requires_png_suffix(tmp_path):
    with pytest.raises(ValueError, match="must use a .png filename"):
        render_answer_image(
            image_path=tmp_path / "answer.jpg",
            question="Question",
            answer_text="Answer",
            sources=[],
        )


def test_an_escape_a_model_wrote_as_text_becomes_the_character():
    """Live, `√-27` came back as `3i×sqrt(3)`.

    Six literal characters where a multiplication sign belongs. Nothing
    downstream expected it: `keyboard_entry_for_math` split the escape into
    variables, the add-on's answer pattern refuses a backslash outright, and
    the whole answer was dropped -- leaving the panel showing the
    backslash-stripped remains, `3iu00d7sqrt(3)`, with Insert disabled.
    """
    assert extract_final_math("FINAL ANSWER: 3i\\u00d7sqrt(3)") == "3i×sqrt(3)"
    assert keyboard_entry_for_math("3i×sqrt(3)") == "3*i*sqrt(3)"

    # The other shape the same model produced, for a radical.
    assert extract_final_math("FINAL ANSWER: 3i\\u221a5") == "3i√5"


def test_decoding_escapes_leaves_latex_alone():
    """LaTeX has no `\\uXXXX` control sequence, and the commands that start
    with `\\u` all fail the four-hex-digit test on their second character."""
    assert (
        extract_final_math("FINAL ANSWER: \\underline{x} + \\upsilon")
        == "\\underline{x} + \\upsilon"
    )
