"""Safe deterministic expansion for polynomial product image questions."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from fractions import Fraction
import re

from .ollama_client import AnswerCallResult, OllamaDebugInfo


Monomial = tuple[tuple[str, int], ...]
Polynomial = dict[Monomial, Fraction]


@dataclass(frozen=True)
class PolynomialExpansion:
    original: str
    expanded: str


def answer_polynomial_product(question: str) -> AnswerCallResult | None:
    """Return an exact expansion when the verified question requests a product."""
    lowered = question.lower()
    if not any(
        phrase in lowered
        for phrase in ("find the product", "expand", "multiply the polynomial")
    ):
        return None
    expansion = expand_first_polynomial_expression(question)
    if expansion is None:
        return None
    answer_text = (
        f"Work: {expansion.original} = {expansion.expanded}\n"
        "Verification: Exact polynomial multiplication and collection of like "
        "terms reproduces the product.\n"
        f"FINAL ANSWER: {expansion.expanded}"
    )
    return AnswerCallResult(
        raw_prompt=question,
        raw_response=answer_text,
        debug_info=OllamaDebugInfo(
            prompt_char_length=len(question),
            schema_top_level_keys=[],
            format_kind="deterministic_polynomial",
            num_predict=0,
            num_ctx=0,
            response_summary={
                "done": True,
                "done_reason": "deterministic",
                "eval_count": 0,
                "message_content_length": len(answer_text),
            },
        ),
    )


def expand_first_polynomial_expression(text: str) -> PolynomialExpansion | None:
    for candidate in _expression_candidates(text):
        try:
            polynomial = _parse_polynomial(candidate)
        except (SyntaxError, TypeError, ValueError, ZeroDivisionError):
            continue
        expanded = _format_polynomial(polynomial)
        if expanded and _normal_display(candidate) != expanded.replace(" ", ""):
            return PolynomialExpansion(
                original=_normal_display(candidate),
                expanded=expanded,
            )
    return None


def _expression_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    for line in text.splitlines():
        stripped = line.strip().strip("$`").rstrip(".,;")
        if "(" in stripped:
            stripped = stripped[stripped.find("(") :]
        if (
            stripped
            and "(" in stripped
            and ")" in stripped
            and re.search(r"[A-Za-z]", stripped)
            and ("^" in stripped or ")(" in stripped.replace(" ", ""))
        ):
            if stripped not in candidates:
                candidates.append(stripped)
    return candidates


def _parse_polynomial(expression: str) -> Polynomial:
    python_expression = _python_expression(expression)
    tree = ast.parse(python_expression, mode="eval")
    return _evaluate(tree.body)


def _python_expression(expression: str) -> str:
    normalized = _normal_display(expression)
    normalized = re.sub(r"(?<=\d)(?=[A-Za-z(])", "*", normalized)
    normalized = re.sub(r"(?<=[A-Za-z)])(?=[A-Za-z\d(])", "*", normalized)
    return normalized.replace("^", "**")


def _normal_display(expression: str) -> str:
    normalized = expression.strip().strip("$`")
    normalized = normalized.replace("−", "-").replace("–", "-")
    normalized = normalized.replace(r"\left", "").replace(r"\right", "")
    normalized = normalized.replace(r"\cdot", "*").replace("·", "*").replace("×", "*")
    normalized = re.sub(
        r"[⁰¹²³⁴⁵⁶⁷⁸⁹]+",
        lambda match: (
            "^" + match.group(0).translate(str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789"))
        ),
        normalized,
    )
    return re.sub(r"\s+", "", normalized)


def _evaluate(node: ast.AST) -> Polynomial:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return {(): Fraction(str(node.value))}
    if isinstance(node, ast.Name) and len(node.id) == 1 and node.id.isalpha():
        return {((node.id, 1),): Fraction(1)}
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _evaluate(node.operand)
        return value if isinstance(node.op, ast.UAdd) else _scale(value, Fraction(-1))
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.Add):
            return _add(_evaluate(node.left), _evaluate(node.right))
        if isinstance(node.op, ast.Sub):
            return _add(
                _evaluate(node.left), _scale(_evaluate(node.right), Fraction(-1))
            )
        if isinstance(node.op, ast.Mult):
            return _multiply(_evaluate(node.left), _evaluate(node.right))
        if isinstance(node.op, ast.Div):
            denominator = _evaluate(node.right)
            if set(denominator) != {()}:
                raise ValueError("polynomial division is unsupported")
            return _scale(_evaluate(node.left), 1 / denominator[()])
        if isinstance(node.op, ast.Pow):
            exponent = _constant_nonnegative_integer(node.right)
            result: Polynomial = {(): Fraction(1)}
            base = _evaluate(node.left)
            for _ in range(exponent):
                result = _multiply(result, base)
            return result
    raise ValueError(f"unsupported polynomial syntax: {type(node).__name__}")


def _constant_nonnegative_integer(node: ast.AST) -> int:
    if not isinstance(node, ast.Constant) or not isinstance(node.value, int):
        raise ValueError("polynomial exponent must be an integer")
    if node.value < 0 or node.value > 12:
        raise ValueError("polynomial exponent is outside the safe range")
    return node.value


def _scale(polynomial: Polynomial, factor: Fraction) -> Polynomial:
    return {
        monomial: coefficient * factor
        for monomial, coefficient in polynomial.items()
        if coefficient * factor
    }


def _add(left: Polynomial, right: Polynomial) -> Polynomial:
    result = dict(left)
    for monomial, coefficient in right.items():
        result[monomial] = result.get(monomial, Fraction(0)) + coefficient
        if not result[monomial]:
            del result[monomial]
    return result


def _multiply(left: Polynomial, right: Polynomial) -> Polynomial:
    result: Polynomial = {}
    for left_monomial, left_coefficient in left.items():
        for right_monomial, right_coefficient in right.items():
            powers: dict[str, int] = dict(left_monomial)
            for variable, exponent in right_monomial:
                powers[variable] = powers.get(variable, 0) + exponent
            monomial = tuple(sorted(powers.items()))
            result[monomial] = result.get(monomial, Fraction(0)) + (
                left_coefficient * right_coefficient
            )
    return {
        monomial: coefficient for monomial, coefficient in result.items() if coefficient
    }


def _format_polynomial(polynomial: Polynomial) -> str:
    ordered = sorted(
        polynomial.items(),
        key=lambda item: (
            -sum(exponent for _, exponent in item[0]),
            tuple((-exponent, variable) for variable, exponent in item[0]),
        ),
    )
    parts: list[str] = []
    for monomial, coefficient in ordered:
        sign = "-" if coefficient < 0 else "+"
        magnitude = abs(coefficient)
        variable_text = "".join(
            variable if exponent == 1 else f"{variable}^{exponent}"
            for variable, exponent in monomial
        )
        if variable_text and magnitude == 1:
            term = variable_text
        else:
            coefficient_text = (
                str(magnitude.numerator)
                if magnitude.denominator == 1
                else f"({magnitude.numerator}/{magnitude.denominator})"
            )
            term = f"{coefficient_text}{variable_text}"
        if not parts:
            parts.append(f"-{term}" if sign == "-" else term)
        else:
            parts.append(f" {sign} {term}")
    return "".join(parts) or "0"
