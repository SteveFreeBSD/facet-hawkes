"""Render grounded answers and math-symbol entry commands as PNG cards."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import subprocess


@dataclass(frozen=True)
class SymbolCommand:
    label: str
    symbol: str
    keyboard: str
    latex: str


@dataclass(frozen=True)
class AnswerImageArtifacts:
    image_path: Path
    keys_path: Path | None


SYMBOL_COMMANDS = (
    (r"\\frac|/", SymbolCommand("Fraction", "a/b", "(a)/(b)", r"\frac{a}{b}")),
    (
        r"\\sqrt\[3\]|∛|\bcbrt\s*\(",
        SymbolCommand("Cube root", "∛x", "Use the Hawkes ∛ template", r"\sqrt[3]{x}"),
    ),
    (
        r"\\sqrt(?!\[)|√|\bsqrt\s*\(",
        SymbolCommand("Square root", "√x", "sqrt(x)", r"\sqrt{x}"),
    ),
    (r"\^|[⁰¹²³⁴⁵⁶⁷⁸⁹]", SymbolCommand("Exponent", "x²", "x^2", r"x^{2}")),
    (r"\\pi|π|\bpi\b", SymbolCommand("Pi", "π", "pi", r"\pi")),
    (r"\\theta|θ|\btheta\b", SymbolCommand("Theta", "θ", "theta", r"\theta")),
    (r"\\leq?|≤|<=", SymbolCommand("Less than or equal", "≤", "<=", r"\le")),
    (
        r"\\geq?|≥|>=",
        SymbolCommand("Greater than or equal", "≥", ">=", r"\ge"),
    ),
    (r"\\ne(q)?|≠|!=", SymbolCommand("Not equal", "≠", "!=", r"\ne")),
    (r"\\pm|±|\+/-", SymbolCommand("Plus or minus", "±", "+/-", r"\pm")),
    (r"\\infty|∞", SymbolCommand("Infinity", "∞", "infinity", r"\infty")),
    (
        r"\\times|\\cdot|×|·|(?<!\*)\*(?!\*)",
        SymbolCommand("Multiply", "×", "*", r"\times"),
    ),
    (r"\\div|÷", SymbolCommand("Divide", "÷", "/", r"\div")),
    (r"\\circ|°", SymbolCommand("Degrees", "°", "degrees", r"^{\circ}")),
    (r"\\cup|∪", SymbolCommand("Union", "∪", "U", r"\cup")),
    (r"\\cap|∩", SymbolCommand("Intersection", "∩", "intersection", r"\cap")),
)

_SUPERSCRIPTS = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")
_SUBSCRIPTS = str.maketrans("-0123456789", "₋₀₁₂₃₄₅₆₇₈₉")


def symbol_commands_for(answer_text: str) -> list[SymbolCommand]:
    return [
        command
        for pattern, command in SYMBOL_COMMANDS
        if re.search(pattern, answer_text, flags=re.IGNORECASE)
    ]


def linearize_math(text: str) -> str:
    """Convert common LaTeX notation to exact, readable Unicode/linear math."""
    replacements = {
        r"\times": "×",
        r"\div": "÷",
        r"\pm": "±",
        r"\neq": "≠",
        r"\ne": "≠",
        r"\leq": "≤",
        r"\le": "≤",
        r"\geq": "≥",
        r"\ge": "≥",
        r"\pi": "π",
        r"\theta": "θ",
        r"\infty": "∞",
        r"\cup": "∪",
        r"\cap": "∩",
        r"\cdot": "·",
    }
    rendered = text
    for source, target in replacements.items():
        rendered = rendered.replace(source, target)
    rendered = re.sub(r"(?<!\\)\bfrac\{", r"\\frac{", rendered)
    rendered = re.sub(
        r"\^\{(-?\d+)\}",
        lambda match: match.group(1).translate(_SUPERSCRIPTS),
        rendered,
    )
    for _ in range(3):
        rendered = re.sub(
            r"\\frac\{([^{}]+)\}\{([^{}]+)\}",
            r"\1⁄(\2)",
            rendered,
        )
        rendered = re.sub(
            r"\\sqrt\[(\d+)\]\{([^{}]+)\}",
            lambda match: _indexed_root_text(match.group(1), match.group(2)),
            rendered,
        )
        rendered = re.sub(r"\\sqrt\{([^{}]+)\}", r"√(\1)", rendered)
        rendered = re.sub(r"\\boxed\{([^{}]+)\}", r"\1", rendered)
    rendered = re.sub(
        r"_\{(-?\d+)\}",
        lambda match: match.group(1).translate(_SUBSCRIPTS),
        rendered,
    )
    rendered = re.sub(
        r"\^(-?\d)",
        lambda match: match.group(1).translate(_SUPERSCRIPTS),
        rendered,
    )
    rendered = rendered.replace(r"^{\circ}", "°").replace(r"^\circ", "°")
    rendered = rendered.replace(r"\(", "").replace(r"\)", "")
    rendered = rendered.replace(r"\[", "").replace(r"\]", "")
    rendered = rendered.replace(r"\left", "").replace(r"\right", "")
    rendered = rendered.replace(r"\ ", " ")
    rendered = rendered.replace("**", "").replace("`", "")
    rendered = rendered.replace("$", "")
    rendered = re.sub(r"⁄\((\d+)\)", r"⁄\1", rendered)
    return re.sub(r"([∛∜])\(([A-Za-z0-9]+)\)", r"\1\2", rendered)


def _indexed_root_text(index: str, radicand: str) -> str:
    if index == "2":
        return f"√({radicand})"
    if index == "3":
        return f"∛({radicand})"
    if index == "4":
        return f"∜({radicand})"
    superscript_index = index.translate(_SUPERSCRIPTS)
    return f"{superscript_index}√({radicand})"


def build_key_command_text(answer_text: str) -> str:
    commands = symbol_commands_for(answer_text)
    lines = ["HOW TO TYPE THE SYMBOLS", ""]
    if not commands:
        lines.append("No special symbol commands are needed; type the answer as shown.")
        return "\n".join(lines)
    for command in commands:
        lines.append(f"{command.symbol}  {command.label}")
        lines.append(f"  Keyboard/homework entry: {command.keyboard}")
        lines.append(f"  LaTeX: {command.latex}")
    return "\n".join(lines)


_ESCAPED_UNICODE = re.compile(r"\\u([0-9a-fA-F]{4})")


def _decode_escaped_unicode(text: str) -> str:
    r"""Turn an escape a model wrote out as text back into the character.

    Live, `√-27` came back as `3i×sqrt(3)`: six literal characters where a
    multiplication sign belongs. A model asked for one line of mathematics will
    sometimes emit JSON's escape form, and nothing downstream expects it --
    `keyboard_entry_for_math` mangled it further into `3*i\u*221*a*5`, and the
    add-on's answer pattern refuses a backslash outright, so the whole answer
    was dropped and the panel showed the backslash-stripped remains.

    Safe against LaTeX, which has no `\uXXXX` control sequence: `\underline`
    and `\upsilon` both fail the four-hex-digit test on their second character.
    """
    return _ESCAPED_UNICODE.sub(lambda match: chr(int(match.group(1), 16)), text)


def extract_final_math(answer_text: str) -> str | None:
    """Extract the solver's final displayed expression for a compact answer card."""
    answer_text = _decode_escaped_unicode(answer_text)
    boxed_start = answer_text.rfind(r"\boxed{")
    if boxed_start >= 0:
        content_start = boxed_start + len(r"\boxed{")
        depth = 1
        for index in range(content_start, len(answer_text)):
            character = answer_text[index]
            if character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    return answer_text[content_start:index].strip()

    matches = list(re.finditer(r"(?im)^\s*FINAL ANSWER:\s*(.+?)\s*$", answer_text))
    if matches:
        return matches[-1].group(1).strip().strip("$`")
    return None


def keyboard_entry_for_math(math_text: str) -> str:
    """Convert common displayed math into explicit ASCII homework syntax."""
    entry = linearize_math(math_text)
    # A conventional coefficient before a radical is implicit multiplication:
    # `y√30` means `y*sqrt(30)`. Insert the boundary while the radical sign is
    # still present, or the later word splitter sees `ysqrt` as five variables.
    entry = re.sub(r"(?<=[A-Za-z0-9)])(?=[√∛∜])", "*", entry)
    # Radical signs are display notation. Homework entry needs the function
    # form, and it has to happen before implicit multiplication is inserted or
    # "√5√x" becomes a product of single letters.
    for _ in range(3):
        entry = re.sub(r"√\(([^()]*)\)", r"sqrt(\1)", entry)
        entry = re.sub(r"∛\(([^()]*)\)", r"cbrt(\1)", entry)
        entry = re.sub(r"∜\(([^()]*)\)", r"(\1)^(1/4)", entry)
        entry = re.sub(r"√([A-Za-z0-9]+)", r"sqrt(\1)", entry)
        entry = re.sub(r"∛([A-Za-z0-9]+)", r"cbrt(\1)", entry)
        entry = re.sub(r"∜([A-Za-z0-9]+)", r"(\1)^(1/4)", entry)
    entry = re.sub(
        r"([⁰¹²³⁴⁵⁶⁷⁸⁹]+)",
        lambda match: (
            "^" + match.group(1).translate(str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789"))
        ),
        entry,
    )
    entry = (
        entry.replace("×", "*")
        .replace("·", "*")
        .replace("÷", "/")
        .replace("⁄", "/")
        .replace("±", "+/-")
    )
    entry = re.sub(r"\s+", "", entry).rstrip(".,;")
    entry = re.sub(r"(?<=\d)(?=[A-Za-z(])", "*", entry)
    functions_and_constants = {
        "sqrt",
        "cbrt",
        "sin",
        "cos",
        "tan",
        "log",
        "ln",
        "abs",
        "pi",
        "theta",
        "infinity",
    }
    entry = re.sub(
        r"[A-Za-z]{2,}",
        lambda match: (
            match.group(0)
            if match.group(0).lower() in functions_and_constants
            else "*".join(match.group(0))
        ),
        entry,
    )
    entry = re.sub(r"(?<=[A-Za-z)])(?=[\d(])", "*", entry)
    entry = re.sub(r"(?<=\))(?=[A-Za-z])", "*", entry)
    for function_name in ("sqrt", "cbrt", "sin", "cos", "tan", "log", "ln", "abs"):
        entry = entry.replace(f"{function_name}*(", f"{function_name}(")
    return entry


def answer_card_answer_text(
    answer_text: str, *, include_keyboard_entry: bool = True
) -> str:
    """Prefer a concise final result and entry while retaining prose-only answers."""
    final_math = extract_final_math(answer_text)
    if final_math is None:
        return answer_text
    if not include_keyboard_entry:
        return visual_math_answer(final_math)
    keyboard_entry = keyboard_entry_for_math(final_math)
    return f"FINAL ANSWER: {final_math}\n\nKEYBOARD ENTRY: {keyboard_entry}"


def visual_math_answer(math_text: str) -> str:
    """Render only the mathematical answer, using a stacked fraction when needed."""
    normalized = math_text.strip().strip("$`")
    fraction = re.fullmatch(r"\\?frac\{([^{}]+)\}\{([^{}]+)\}", normalized)
    if fraction is not None:
        numerator, denominator = fraction.groups()
        numerator = linearize_math(numerator)
        denominator = linearize_math(denominator)
        fraction_bar = "─" * max(len(numerator), len(denominator), 3)
        return f"{numerator}\n{fraction_bar}\n{denominator}"
    linear_fraction = re.fullmatch(r"(.+?)/\((.+)\)", normalized)
    if linear_fraction is not None:
        numerator, denominator = linear_fraction.groups()
        numerator = linearize_math(numerator)
        denominator = linearize_math(denominator)
        fraction_bar = "─" * max(len(numerator), len(denominator), 3)
        return f"{numerator}\n{fraction_bar}\n{denominator}"
    return linearize_math(normalized)


def build_answer_card_text(
    *,
    question: str,
    answer_text: str,
    sources: list[str],
    include_key_commands: bool = True,
) -> str:
    if not include_key_commands:
        final_math = extract_final_math(answer_text)
        return visual_math_answer(final_math or answer_text)
    card_answer = answer_card_answer_text(
        answer_text, include_keyboard_entry=include_key_commands
    )
    source_text = "\n".join(f"• {source}" for source in sources) or "• none"
    sections = [
        "PRECALCULUS ANSWER",
        f"QUESTION\n{linearize_math(question)}",
        f"ANSWER\n{linearize_math(card_answer)}",
    ]
    if include_key_commands:
        sections.append(build_key_command_text(card_answer))
    sections.append(f"SOURCES\n{source_text}")
    return "\n\n".join(sections)


def render_answer_image(
    *,
    image_path: Path,
    question: str,
    answer_text: str,
    sources: list[str],
    include_key_commands: bool = True,
) -> AnswerImageArtifacts:
    image_path = image_path.expanduser().resolve()
    if image_path.suffix.lower() != ".png":
        raise ValueError("--answer-image must use a .png filename")
    renderer = shutil.which("pango-view")
    if renderer is None:
        raise RuntimeError("pango-view is required to render answer images")
    image_path.parent.mkdir(parents=True, exist_ok=True)
    card_text = build_answer_card_text(
        question=question,
        answer_text=answer_text,
        sources=sources,
        include_key_commands=include_key_commands,
    )
    card_answer = answer_card_answer_text(answer_text)
    subprocess.run(
        [
            renderer,
            "--no-display",
            f"--output={image_path}",
            "--background=#f8fafc",
            "--foreground=#111827",
            (
                "--font=Noto Sans 16"
                if include_key_commands
                else "--font=Noto Sans Mono 32"
            ),
            f"--width={760 if include_key_commands else 480}",
            *([] if include_key_commands else ["--align=center"]),
            "--wrap=word-char",
            "--margin=32",
            "--spacing=6",
            f"--text={card_text}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    keys_path = None
    if include_key_commands:
        keys_path = image_path.with_suffix(".keys.txt")
        keys_path.write_text(
            build_key_command_text(card_answer) + "\n", encoding="utf-8"
        )
    return AnswerImageArtifacts(image_path=image_path, keys_path=keys_path)
