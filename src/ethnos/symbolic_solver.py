"""Safe exact SymPy operations for verified screenshot transcriptions."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from fractions import Fraction
import re

import sympy

from .ollama_client import AnswerCallResult, OllamaDebugInfo


#: Operations that rearrange a polynomial without rewriting it. They are the
#: only ones whose answer may legitimately equal their input.
ORDERING = frozenset({"descending_order", "ascending_order"})

#: Operations that report a property of the polynomial rather than another way
#: of writing it. Their answer is a number, so it is deliberately *not* equal
#: to the input and the equivalence check does not apply to them.
EXTRACTION = frozenset(
    {"degree", "leading_coefficient", "constant_term", "classify", "evaluate"}
)


@dataclass(frozen=True)
class SymbolicResult:
    operation: str
    original: str
    answer: str


def answer_symbolic_math(
    *, problem_text: str, expressions: list[str]
) -> AnswerCallResult | None:
    """Return an exact factor/expansion, or None for unsupported questions."""
    operation = _requested_operation(problem_text)
    if operation is None:
        return None
    result = solve_symbolic_operation(
        operation=operation,
        problem_text=problem_text,
        expressions=expressions,
    )
    if result is None:
        return None
    verification = {
        "factor": (
            "SymPy exact factorization and reverse expansion agree, or the "
            "polynomial is prime and the question offers that answer."
        ),
        "gcf": (
            "SymPy removed the greatest common factor only, and the product "
            "expands back to the original."
        ),
        "expand": "SymPy exact expansion and reverse factorization agree.",
        "simplify": "SymPy exact evaluation independently confirms the result.",
        "rational_exponents": (
            "SymPy exact evaluation confirms the result, written with "
            "fractional exponents as the question requires."
        ),
        "descending_order": (
            "SymPy ordered the same polynomial by descending powers; the terms "
            "are unchanged."
        ),
        "ascending_order": (
            "SymPy ordered the same polynomial by ascending powers; the terms "
            "are unchanged."
        ),
        "degree": "SymPy read the degree from the polynomial's own terms.",
        "constant_term": "SymPy evaluated the polynomial where the variable is zero.",
        "classify": "SymPy counted the polynomial's terms.",
        "evaluate": "SymPy substituted the given value exactly.",
        "leading_coefficient": (
            "SymPy took the coefficient of the highest-power term."
        ),
        "rationalize": (
            "SymPy cleared the radical from the denominator and confirmed the "
            "result equals the original."
        ),
    }[operation]
    answer_text = (
        f"Work: {result.original} = {result.answer}\n"
        f"Verification: {verification}\n"
        f"FINAL ANSWER: {result.answer}"
    )
    return AnswerCallResult(
        raw_prompt=problem_text,
        raw_response=answer_text,
        debug_info=OllamaDebugInfo(
            prompt_char_length=len(problem_text),
            schema_top_level_keys=[],
            format_kind="sympy_exact",
            num_predict=0,
            num_ctx=0,
            response_summary={
                "done": True,
                "done_reason": "deterministic",
                "eval_count": 0,
                "operation": operation,
            },
        ),
    )


def solve_symbolic_operation(
    *, operation: str, problem_text: str, expressions: list[str]
) -> SymbolicResult | None:
    """Safely parse candidate polynomials and apply an exact operation."""
    for candidate in _expression_candidates(problem_text, expressions):
        try:
            original = _safe_sympy_expression(
                candidate,
                positive_symbols=_assume_positive(problem_text, candidate, operation),
            )
        except (SyntaxError, TypeError, ValueError, ZeroDivisionError):
            continue
        if operation == "factor":
            answer = sympy.factor(original)
        elif operation == "gcf":
            answer = _factor_out_gcf(original)
        elif operation == "expand":
            answer = sympy.expand(original)
        elif operation in {"simplify", "rational_exponents"}:
            answer = sympy.simplify(original)
        elif operation in EXTRACTION:
            if len(original.free_symbols) != 1:
                continue
            (symbol,) = original.free_symbols
            polynomial = sympy.Poly(original, symbol)
            if operation == "degree":
                answer = sympy.Integer(polynomial.degree())
            elif operation == "leading_coefficient":
                answer = polynomial.LC()
            elif operation == "constant_term":
                # The coefficient of x^0, which is not the same as the last
                # term written: an ordered polynomial may simply have none.
                answer = polynomial.as_expr().subs(symbol, 0)
            elif operation == "classify":
                names = {1: "monomial", 2: "binomial", 3: "trinomial"}
                count = len(polynomial.as_expr().as_ordered_terms())
                if count not in names:
                    continue
                answer = sympy.Symbol(names[count])
            else:
                value = _substitution(problem_text.lower())
                if value is None or value[0] != symbol.name:
                    continue
                answer = sympy.nsimplify(original.subs(symbol, sympy.Rational(value[1])))
        elif operation in {"descending_order", "ascending_order"}:
            # "Descending order" names a single variable's powers. With two or
            # more symbols the intended ordering is genuinely ambiguous, so
            # this hands the question back rather than guessing at it.
            if len(original.free_symbols) != 1:
                continue
            answer = original
        elif operation == "rationalize":
            # radsimp is the operation actually being asked for: it clears the
            # radical from the denominator. Plain simplify returns an
            # equivalent form that is still irrational underneath, which is not
            # the requested answer.
            answer = sympy.radsimp(original)
        else:
            raise ValueError(f"Unsupported symbolic operation: {operation}")
        # An extraction answers a question *about* the polynomial, so its answer
        # is a number and is meant to differ from the input. Every other
        # operation must still be the same value, rearranged.
        if operation not in EXTRACTION and not _equivalent(original, answer):
            continue
        ordering = operation in ORDERING
        original_text = (
            _input_display(candidate)
            if ordering
            or operation in EXTRACTION
            or operation in {"expand", "simplify", "rationalize", "rational_exponents"}
            else _display(original)
        )
        if operation == "rational_exponents":
            answer_text = _display_rational_powers(answer)
        elif ordering:
            answer_text = _display_ordered(
                answer, descending=operation == "descending_order"
            )
        else:
            answer_text = _display(answer)
        # Every other operation returning its own input has done nothing, and
        # falls through to something that can. A polynomial already written in
        # the requested order is different: it is answered by itself, and
        # rejecting that sent a finished answer down the minute-long fallback.
        if (
            not ordering
            and operation not in EXTRACTION
            and _compact(original_text) == _compact(answer_text)
        ):
            # Factoring is the one rewriting whose input can be its answer: a
            # prime polynomial has no factorization, and these questions say so
            # themselves -- "if it cannot be factored, indicate Not
            # Factorable". Read as a failure, `y^2 + y + 17` cost seventy-six
            # seconds of vision and model for a fact SymPy had at once.
            if operation == "factor" and _offers_not_factorable(problem_text):
                return SymbolicResult(
                    operation=operation,
                    original=original_text,
                    answer="Not Factorable",
                )
            continue
        return SymbolicResult(
            operation=operation,
            original=original_text,
            answer=answer_text,
        )
    return None


def _assume_positive(problem_text: str, candidate: str, operation: str) -> bool:
    """Whether to treat the variables in a radical exercise as non-negative.

    Hawkes marks `sqrt(9y^2)` correct as `3y`, not `3|y|`, which is the usual
    textbook convention for these sections. It matters for rational-exponent
    conversions too: without it, `sqrt(y^3)` stays the nested `(y^3)^(1/2)`
    instead of collapsing to the `y^(3/2)` the question asks for. Without the assumption SymPy
    refuses to extract the root at all and hands the question back as its own
    answer -- observed live on "Simplify the following radical expression"
    over the fifth root of y^5 x^30 z^25.
    """
    if _states_variables_are_positive(problem_text):
        return True
    if operation not in {"simplify", "rationalize", "rational_exponents"}:
        return False
    if operation != "simplify":
        return True
    if not re.search(r"\\sqrt|[√∛∜]|\*\*\(1/", candidate):
        return False
    # An even index is the one case where the assumption changes the answer.
    # The fourth root of y^20 is |y|^5, not y^5: the two differ in sign for
    # every negative y, and the fourth root cannot be negative. Hawkes marked
    # `y^5z^4/3` wrong for exactly this reason on lesson 1.2 question 7. An
    # odd index needs no bars -- the fifth root of y^5 is y for every real y --
    # and the assumption is what lets SymPy extract that root at all, so it
    # stays for odd indices.
    return not _has_even_index_radical(candidate)


def _states_variables_are_positive(problem_text: str) -> bool:
    """Whether the question itself licenses the non-negativity assumption.

    When a question says so, the bars are not wanted and `y^5` is the expected
    answer. When it says nothing, the bars are part of the answer.
    """
    text = problem_text.lower()
    return any(
        phrase in text
        for phrase in (
            "all variables are positive",
            "variables represent positive",
            "variables are positive",
            "assume all variables",
            "positive real numbers",
        )
    )


def _has_even_index_radical(candidate: str) -> bool:
    """Whether the expression takes an even root, whose result may need bars.

    A bare `\\sqrt` and `√` are index two. `\\sqrt[n]` and `**(1/n)` carry their
    index. Anything unrecognised counts as even, because treating an even root
    as odd is the error that produces a wrong answer.
    """
    for index in re.findall(r"\\sqrt\[(\d+)\]", candidate):
        if int(index) % 2 == 0:
            return True
    for index in re.findall(r"\*\*\(1/(\d+)\)", candidate):
        if int(index) % 2 == 0:
            return True
    # A square root written without an index, and the two-character radicals.
    if re.search(r"\\sqrt(?!\[)|√", candidate):
        return True
    if "∜" in candidate:
        return True
    return False


def _equivalent(original: sympy.Expr, answer: sympy.Expr) -> bool:
    """Whether the answer is exactly the original, rearranged.

    `expand` settles polynomials cheaply but cannot prove a radical difference
    is zero, so radical cases fall through to the slower full simplify.
    """
    difference = sympy.expand(original - answer)
    if difference == 0:
        return True
    return sympy.simplify(difference) == 0


def _requested_operation(problem_text: str) -> str | None:
    lowered = problem_text.lower()
    # Questions *about* the polynomial rather than rewritings of it. Live,
    # both arrived as an empty instruction and were answered by the model from
    # a screenshot; SymPy reads them straight off the terms.
    if "leading coefficient" in lowered:
        return "leading_coefficient"
    if "constant term" in lowered:
        return "constant_term"
    # Naming a trinomial is not asking what kind of polynomial it is. "Factor
    # the following trinomial completely" contains the word and is a factoring
    # question; claiming it answered "trinomial" to a request to factor, which
    # the coverage sweep caught before it shipped. A real classification either
    # says so, or offers the choice.
    if re.search(r"\bclassif\w*\b", lowered) or (
        len(re.findall(r"\b(?:monomial|binomial|trinomial)\b", lowered)) >= 2
    ):
        return "classify"
    # "Evaluate the polynomial for x = 2". The value to substitute is in the
    # prompt, so this is only claimed when one is actually there.
    if re.search(r"\bevaluat\w*\b", lowered) and _substitution(lowered) is not None:
        return "evaluate"
    if re.search(r"\bdegree\b", lowered):
        return "degree"
    # Checked first, but only when ordering is the whole request. "Express the
    # polynomial in descending order" asks for a rearrangement and nothing
    # else; live, that prompt matched no verb at all and cost a full minute of
    # vision plus model for a result SymPy already had. "Factor completely and
    # write the answer in descending order" is a different question, and
    # answering it by reordering the unfactored polynomial would be confidently
    # wrong -- so any rewriting verb alongside the ordering wins.
    ordering = next(
        (
            name
            for phrase, name in (
                ("descending order", "descending_order"),
                ("ascending order", "ascending_order"),
            )
            if phrase in lowered
        ),
        None,
    )
    if ordering is not None and not re.search(
        r"\bfactor|\bexpand|\bsimplif|\brationaliz|\bmultiply|\bproduct\b", lowered
    ):
        return ordering
    # Checked before "simplify": these questions say "Simplify ... by
    # rationalizing the denominator", and a generic simplify answers the wrong
    # question while looking plausible.
    if "rational exponent" in lowered:
        return "rational_exponents"
    if "rationaliz" in lowered:
        return "rationalize"
    # Narrower than factoring, and checked first. "Factor out the greatest
    # common factor" asks for one step; `sympy.factor` performs all of them and
    # answers a question that was not asked.
    if "greatest common factor" in lowered or re.search(r"\bgcf\b", lowered):
        return "gcf"
    if "factor" in lowered:
        return "factor"
    # Before "simplify", because these questions say "Multiply the following
    # polynomials and simplify your answer" and mean multiply. Checked the
    # other way round, `simplify` claimed the prompt and SymPy returned the
    # already-simple factored form -- which is to say, the question's own input
    # handed back as its answer.
    if any(
        phrase in lowered
        for phrase in (
            "find the product",
            "expand",
            "multiply the polynomial",
            "multiply the following polynomial",
            "add or subtract the following polynomial",
        )
    ):
        return "expand"
    # Hawkes commonly says "Express your answer in simplified form" rather
    # than using the imperative "Simplify". They request the same exact
    # operation; missing the adjective sent a deterministic radical down the
    # slow fallback path and then reported it unsupported.
    if re.search(r"\bsimplif(?:y|ied|ication)\b", lowered):
        return "simplify"
    return None


def _offers_not_factorable(problem_text: str) -> bool:
    """Whether the question itself names "not factorable" as an answer.

    Only then is an unfactorable polynomial an answer rather than a decline. A
    question that simply says "factor" and cannot be factored is one this
    solver should hand back, not one it should answer with prose.
    """
    lowered = problem_text.lower()
    return "not factorable" in lowered or "cannot be factored" in lowered


def _substitution(lowered: str) -> tuple[str, str] | None:
    """The variable and value in "evaluate ... for x = 2", or None.

    Without one there is nothing to evaluate, and claiming the question would
    mean answering it with the polynomial itself.
    """
    match = re.search(r"\b(?:for|when|at)\s+([a-z])\s*=\s*(-?\d+(?:/\d+)?)", lowered)
    return (match.group(1), match.group(2)) if match else None


def _expression_candidates(problem_text: str, expressions: list[str]) -> list[str]:
    candidates: list[str] = []
    for value in [*expressions, *problem_text.splitlines()]:
        candidate = value.strip().strip("$`").rstrip(".,;")
        candidate = re.sub(
            r"^(?:factor|expand|find the product(?: of)?|multiply)\b[^:]*:\s*",
            "",
            candidate,
            flags=re.IGNORECASE,
        )
        if not re.search(r"[A-Za-z\d]", candidate):
            continue
        if not re.search(r"[+\-*/^()⁰¹²³⁴⁵⁶⁷⁸⁹]|\\sqrt|[√∛∜]", candidate):
            continue
        if candidate not in candidates:
            candidates.append(candidate)
    return sorted(candidates, key=_candidate_score, reverse=True)


def _candidate_score(value: str) -> tuple[int, int]:
    return (len(re.findall(r"[+\-*/]", value)), len(value))


def _safe_sympy_expression(
    expression: str, *, positive_symbols: bool = False
) -> sympy.Expr:
    normalized = _python_expression(expression)
    tree = ast.parse(normalized, mode="eval")
    return _evaluate(tree.body, positive_symbols=positive_symbols)


def _python_expression(expression: str) -> str:
    normalized = expression.strip().strip("$`")
    normalized = normalized.replace("−", "-").replace("–", "-")
    normalized = normalized.replace(r"\left", "").replace(r"\right", "")
    normalized = normalized.replace(r"\cdot", "*").replace("·", "*").replace("×", "*")
    normalized = re.sub(r"\^\{(-?\d+)\}", r"^\1", normalized)
    for _ in range(3):
        normalized = re.sub(
            r"\\frac\{([^{}]+)\}\{([^{}]+)\}",
            lambda match: f"(({match.group(1)})/({match.group(2)}))",
            normalized,
        )
        normalized = re.sub(
            r"\\sqrt\[(\d+)\]\{([^{}]+)\}",
            lambda match: f"(({match.group(2)})**(1/{match.group(1)}))",
            normalized,
        )
        normalized = re.sub(
            r"\\sqrt\{([^{}]+)\}",
            lambda match: f"(({match.group(1)})**(1/2))",
            normalized,
        )
    # After \frac expansion so "^{\frac{1}{6}}" is reachable; the earlier
    # integer-only pass cannot match a braced fraction.
    normalized = re.sub(
        r"\^\{([^{}]+)\}", lambda match: f"**({match.group(1)})", normalized
    )
    normalized = re.sub(
        r"[⁰¹²³⁴⁵⁶⁷⁸⁹]+",
        lambda match: (
            "^" + match.group(0).translate(str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789"))
        ),
        normalized,
    )
    normalized = re.sub(r"\s+", "", normalized)
    normalized = re.sub(r"(?<=\d)(?=[A-Za-z(])", "*", normalized)
    normalized = re.sub(r"(?<=[A-Za-z)])(?=[A-Za-z\d(])", "*", normalized)
    normalized = normalized.replace("^", "**")
    if not re.fullmatch(r"[A-Za-z0-9_+\-*/().]+", normalized):
        raise ValueError("expression contains unsupported characters")
    return normalized


def _evaluate(node: ast.AST, *, positive_symbols: bool = False) -> sympy.Expr:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return sympy.Integer(node.value)
    if isinstance(node, ast.Constant) and isinstance(node.value, float):
        return sympy.Rational(Fraction(str(node.value)))
    if isinstance(node, ast.Name) and len(node.id) == 1 and node.id.isalpha():
        # Real, not unrestricted: an unrestricted symbol may be complex, and
        # SymPy will not extract a root from one -- it handed the fourth root
        # of y^20*z^16/81 back as `(y^20*z^16)^(1/4)/3`, unsimplified. Declared
        # real, the same expression simplifies to `y^4*z^4*|y|/3`, which is the
        # answer with its absolute value intact.
        return (
            sympy.Symbol(node.id, positive=True)
            if positive_symbols
            else sympy.Symbol(node.id, real=True)
        )
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _evaluate(node.operand, positive_symbols=positive_symbols)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp):
        left = _evaluate(node.left, positive_symbols=positive_symbols)
        right = _evaluate(node.right, positive_symbols=positive_symbols)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Pow):
            safe_integer = right.is_Integer and -64 <= int(right) <= 64
            # Any small rational, not only a unit fraction: these sections ask
            # for y^(3/4) as readily as y^(1/4), and the bounds are what keep
            # the evaluation cheap -- a numerator of 1 never had anything to do
            # with it. Rejecting them made "express your answer using rational
            # exponents" unanswerable for most of its own questions.
            safe_rational = (
                right.is_Rational
                and not right.is_Integer
                and abs(int(right.p)) <= 64
                and 2 <= int(right.q) <= 24
            )
            if not (safe_integer or safe_rational):
                raise ValueError("exponent is outside the safe exact range")
            return left**right
    raise ValueError(f"unsupported symbolic syntax: {type(node).__name__}")


def _display(expression: sympy.Expr) -> str:
    numerator, denominator = expression.as_numer_denom()
    # Merged per part, never across the fraction bar: rebuilding the quotient
    # from merged parts lets SymPy pull a root back into the denominator,
    # undoing the merge.
    numerator = _merge_square_roots(numerator)
    denominator = _merge_square_roots(denominator)
    if denominator != 1:
        return f"\\frac{{{_display_basic(numerator)}}}{{{_display_basic(denominator)}}}"
    return _display_basic(numerator)


def _factor_out_gcf(expression: sympy.Expr) -> sympy.Expr:
    """Remove the greatest common factor and stop there.

    `sympy.factor` keeps going and returns a complete factorization, which is a
    different question: asked to take the GCF out of `-10xy^2 - 15xy + 25x` it
    answers `-5x(y - 1)(2y + 5)` where the question wants `-5x(2y^2 + 3y - 5)`.

    The sign follows the usual convention: a leading term that is negative
    comes out with the common factor, so the bracket opens positive.
    """
    factored = sympy.factor_terms(expression)
    if not isinstance(factored, sympy.Mul):
        return factored
    parts = list(factored.args)
    for index, part in enumerate(parts):
        if not isinstance(part, sympy.Add):
            continue
        leading = part.as_ordered_terms()[0]
        if leading.could_extract_minus_sign():
            parts[index] = -part
            return -sympy.Mul(*parts)
        break
    return factored


def _display_ordered(expression: sympy.Expr, *, descending: bool) -> str:
    """Write a polynomial's terms in power order, which is the whole answer.

    Each term is printed by the same helper as everywhere else, so an ordered
    answer carries exactly the notation the rest of the panel uses; only the
    sequence and the joining signs are decided here.
    """
    terms = expression.as_ordered_terms(order="lex")
    if not descending:
        terms = list(reversed(terms))
    rendered = ""
    for term in terms:
        text = _display_basic(term)
        negative = text.startswith("-")
        if negative:
            text = text[1:].lstrip()
        if not rendered:
            rendered = f"-{text}" if negative else text
        else:
            rendered += f" - {text}" if negative else f" + {text}"
    return rendered


def _merge_square_roots(part: sympy.Expr) -> sympy.Expr:
    """Write `sqrt(a)*sqrt(b)` as the single `sqrt(a*b)`.

    SymPy splits a root over a product, and keeps it split. Textbooks -- and
    Hawkes -- write one radical: the answer to `sqrt(6y/(5z))` is
    `sqrt(30yz)/(5z)`, not `sqrt(30)*sqrt(y)*sqrt(z)/(5z)`. This changes only
    how the value is written, never the value.
    """
    roots: list[sympy.Expr] = []
    others: list[sympy.Expr] = []
    for factor in sympy.Mul.make_args(part):
        if isinstance(factor, sympy.Pow) and factor.exp == sympy.Rational(1, 2):
            roots.append(factor.base)
        else:
            others.append(factor)
    if len(roots) < 2:
        return part
    # Built unevaluated throughout: `sqrt(5*x)` splits straight back into
    # `sqrt(5)*sqrt(x)` the moment SymPy evaluates it for a positive symbol.
    radicand = sympy.Mul(*roots, evaluate=False)
    merged = sympy.Pow(radicand, sympy.Rational(1, 2), evaluate=False)
    return sympy.Mul(*others, merged, evaluate=False) if others else merged


def _display_basic(expression: sympy.Expr) -> str:
    value = sympy.sstr(_fold_absolute_powers(expression), order="lex")
    # SymPy prints radicals as function calls. They have to become radical
    # signs before multiplication signs are dropped below, or
    # "sqrt(5)*sqrt(x)" turns into the unreadable "sqrt(5)sqrt(x)".
    for _ in range(3):
        value = re.sub(
            r"\bsqrt\(([^()]*)\)",
            lambda match: _display_root(match.group(1), "2"),
            value,
        )
        value = re.sub(
            r"\bcbrt\(([^()]*)\)",
            lambda match: _display_root(match.group(1), "3"),
            value,
        )
    # Put a simple symbolic factor before a radical. SymPy prints
    # `sqrt(30)*y`; dropping `*` would make `√30y`, and the editor planner must
    # read that as sqrt(30y). `y*√30` is unambiguous and also lets Hawkes attach
    # the radical after y instead of relying on its fragile continuation slot.
    root = r"((?:[⁰¹²³⁴⁵⁶⁷⁸⁹]+)?[√∛∜](?:\([^()]*\)|[A-Za-z0-9]+))"
    factor = r"([A-Za-z](?:\*\*\d+)?)"
    for _ in range(3):
        value = re.sub(rf"{root}\*{factor}", r"\2*\1", value)
    # If a more complex following factor could not be reordered, retain an
    # explicit radical boundary rather than emitting ambiguous adjacency.
    value = re.sub(r"([√∛∜])([A-Za-z0-9]+)(?=\*)", r"\1(\2)", value)
    value = re.sub(
        r"([A-Za-z0-9]+)\*\*\(1/(\d+)\)",
        lambda match: _display_root(match.group(1), match.group(2)),
        value,
    )
    value = _display_absolute_values(value)
    return value.replace("**", "^").replace("*", "")


def _fold_absolute_powers(expression: sympy.Expr) -> sympy.Expr:
    """Gather `y**4*Abs(y)` back into `Abs(y)**5`.

    SymPy factors the fourth root of `y**20` as `y**4*Abs(y)`, which is right
    but is not the form the answer is written in. For real y, `y**2 = |y|**2`,
    so an even power of y beside a power of `|y|` is one power of `|y|`. The
    factors need not be adjacent -- `y**4*z**4*Abs(y)` is `|y|**5*z**4` -- so
    this works on the expression rather than on its printed form.

    Only expressions that actually contain an `Abs` are touched: for a symbol
    declared positive SymPy simplifies `Abs(x)` to `x`, and an earlier version
    that looked up `Abs(x)` regardless mistook `x**6` for a barred factor and
    dropped it, turning `x^6yz^5` into `yz^5`.
    """
    if not isinstance(expression, sympy.Mul) or not expression.has(sympy.Abs):
        return expression
    barred: dict[sympy.Expr, sympy.Expr] = {}
    plain: dict[sympy.Expr, sympy.Expr] = {}
    rest = []
    for factor in expression.args:
        base, exponent = factor.as_base_exp()
        if isinstance(base, sympy.Abs):
            inner = base.args[0]
            barred[inner] = barred.get(inner, sympy.Integer(0)) + exponent
        elif base.is_Symbol:
            plain[base] = plain.get(base, sympy.Integer(0)) + exponent
        else:
            rest.append(factor)
    merged = []
    for inner, bars in barred.items():
        extra = plain.pop(inner, sympy.Integer(0))
        # Only an even plain power is the same as that power of the bars.
        absorbed = extra if extra.is_even else sympy.Integer(0)
        total = bars + absorbed
        merged.append(
            sympy.Abs(inner)
            if total == 1
            else sympy.Pow(sympy.Abs(inner), total, evaluate=False)
        )
        if absorbed == 0 and extra != 0:
            merged.append(sympy.Pow(inner, extra, evaluate=False))
    for symbol, exponent in plain.items():
        merged.append(symbol if exponent == 1 else sympy.Pow(symbol, exponent, evaluate=False))
    return sympy.Mul(*rest, *merged, evaluate=False)


def _display_absolute_values(value: str) -> str:
    """Print SymPy's `Abs(y)` as bars, with any power inside them.

    `|y|**5` and `|y**5|` are the same number for every real y, but they are
    not the same to build: the Hawkes editor raises an exponent on the box the
    cursor is in, so bars-around-the-power puts the exponent on `y`, inside the
    bars, which is the path the planner already drives. Bars-then-exponent
    would have to attach a power to a closed group.
    """
    value = re.sub(
        r"\bAbs\(([^()]*)\)\*\*(\d+)",
        lambda match: f"|{match.group(1)}**{match.group(2)}|",
        value,
    )
    return re.sub(r"\bAbs\(([^()]*)\)", lambda match: f"|{match.group(1)}|", value)


def _display_rational_powers(expression: sympy.Expr) -> str:
    """Render radicals as fractional exponents.

    SymPy prints `a**Rational(1, 2)` as `sqrt(a)` and will not rewrite it back,
    so the inverse is done on the printed form. Questions that say "express
    your answer using rational exponents" are marked wrong for a radical.
    """
    value = sympy.sstr(expression, order="lex")
    for _ in range(3):
        value = re.sub(r"\bsqrt\(([^()]*)\)", r"(\1)**(1/2)", value)
        value = re.sub(r"\bcbrt\(([^()]*)\)", r"(\1)**(1/3)", value)
    # A single symbol or number needs no parentheses around it.
    value = re.sub(r"\(([A-Za-z0-9]+)\)\*\*", r"\1**", value)
    return value.replace("**", "^").replace("*", "")


def _display_root(radicand: str, index: str) -> str:
    # A compound radicand needs grouping, or "√5*x" reads as "(√5)·x".
    body = radicand if re.fullmatch(r"[A-Za-z0-9]+", radicand) else f"({radicand})"
    if index == "2":
        return f"√{body}"
    if index == "3":
        return f"∛{body}"
    if index == "4":
        return f"∜{body}"
    superscripts = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
    return f"{index.translate(superscripts)}√{body}"


def _input_display(expression: str) -> str:
    value = expression.strip().strip("$`")
    value = value.replace("−", "-").replace("–", "-")
    value = re.sub(r"\^\{(-?\d+)\}", r"^\1", value)
    return re.sub(r"\s+", "", value)


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value)
