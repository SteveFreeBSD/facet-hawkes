"""Read a Hawkes question from its MathML instead of from a screenshot.

Hawkes renders questions with MathJax, which leaves the expression in the page
as presentation MathML. Reading that is exact, costs nothing, and skips the two
independent image transcriptions that are otherwise almost the whole of a
solve. It also removes a class of error outright: a model cannot misread an
exponent that was never rendered to pixels.

The output is the LaTeX-ish form `symbolic_solver` already accepts, so nothing
downstream changes.

Screenshots remain the fallback. A question drawn as an image, or one whose
MathML is missing or beyond this converter, still goes through vision.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree

# MathJax emits these for operators; the solver wants plain ASCII or its own
# LaTeX spellings.
OPERATORS = {
    "⋅": "*",  # dot operator
    "·": "*",  # middle dot
    "×": "*",  # multiplication sign
    "−": "-",  # minus sign
    "–": "-",  # en dash
    "⁄": "/",  # fraction slash
    "÷": "/",
    "⁡": "",  # function application (invisible)
    "⁢": "*",  # invisible times
    "⁣": "",  # invisible separator
    "±": r"\pm",
    "≤": r"\leq",
    "≥": r"\geq",
    "≠": r"\neq",
}


class UnsupportedMathML(ValueError):
    """The expression uses MathML this converter does not handle."""


def mathml_to_latex(markup: str) -> str:
    """Convert presentation MathML to the LaTeX subset the solver parses.

    @raises UnsupportedMathML: when an element has no faithful translation.
    Guessing would produce a plausible expression that is not the question.
    """
    try:
        root = ElementTree.fromstring(markup.strip())
    except ElementTree.ParseError as error:
        raise UnsupportedMathML(f"unparseable MathML: {error}") from error
    latex = _convert(root).strip()
    if not latex:
        raise UnsupportedMathML("MathML contained no expression")
    return _tidy(latex)


def _tag(element) -> str:
    """Local name, without the MathML namespace."""
    return element.tag.rsplit("}", 1)[-1].lower()


def _text(element) -> str:
    return (element.text or "").strip()


def _children(element) -> list:
    # Annotations carry alternative encodings of the same expression; taking
    # them as well would duplicate everything.
    return [
        child
        for child in element
        if _tag(child) not in {"annotation", "annotation-xml"}
    ]


def _join(element) -> str:
    return "".join(_convert(child) for child in _children(element))


def _brace(value: str) -> str:
    """Wrap an exponent or subscript in braces unless it is one character."""
    return value if re.fullmatch(r"[A-Za-z0-9]", value) else f"{{{value}}}"


def _base(value: str) -> str:
    """Parenthesise the base of a power unless it is a single token.

    `<msup><mrow><mo>-</mo><mn>2</mn></mrow><mn>6</mn></msup>` is `(-2)^6`,
    which is 64. Emitting `-2^6` instead reads as `-(2^6)`, which is -64: the
    grouping the MathML carried is the whole difference between the two.
    """
    if re.fullmatch(r"[A-Za-z0-9]+", value) or re.fullmatch(r"\(.*\)", value):
        return value
    return f"({value})"


def _convert(element) -> str:
    tag = _tag(element)

    if tag in {"math", "mstyle", "mrow", "semantics", "mpadded", "menclose"}:
        return _join(element)
    if tag in {"mi", "mn"}:
        return _text(element)
    if tag == "mo":
        raw = _text(element)
        return OPERATORS.get(raw, raw)
    if tag == "mtext":
        return _text(element)
    if tag in {"mspace", "none"}:
        return ""

    parts = [_convert(child) for child in _children(element)]

    if tag == "mfrac" and len(parts) == 2:
        return f"\\frac{{{parts[0]}}}{{{parts[1]}}}"
    if tag == "msup" and len(parts) == 2:
        return f"{_base(parts[0])}^{_brace(parts[1])}"
    if tag == "msub" and len(parts) == 2:
        return f"{_base(parts[0])}_{_brace(parts[1])}"
    if tag == "msqrt":
        return f"\\sqrt{{{''.join(parts)}}}"
    if tag == "mroot" and len(parts) == 2:
        return f"\\sqrt[{parts[1]}]{{{parts[0]}}}"
    if tag == "mfenced":
        return f"({''.join(parts)})"

    raise UnsupportedMathML(f"unhandled MathML element <{tag}>")


def _tidy(latex: str) -> str:
    """Remove the spacing MathJax adds, which the parser does not want."""
    return re.sub(r"\s+", "", latex)
