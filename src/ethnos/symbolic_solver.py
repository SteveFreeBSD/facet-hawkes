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
        imaginary_unit = _uses_imaginary_unit(problem_text, candidate, operation)
        try:
            original = _safe_sympy_expression(
                candidate,
                positive_symbols=_assume_positive(problem_text, candidate, operation),
                imaginary_unit=imaginary_unit,
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
            # SymPy leaves a numeric complex power such as ``(2 + I)**2``
            # intact under simplify. The I may come from contextual lowercase
            # `i` or from a negative radical. When no variables remain,
            # ordinary expansion is exact evaluation and produces the
            # requested simplest ``a + bi`` form.
            if not original.free_symbols and original.has(sympy.I):
                answer = sympy.simplify(sympy.expand(original))
            else:
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
                answer = sympy.nsimplify(
                    original.subs(symbol, sympy.Rational(value[1]))
                )
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
            and _same_expression_text(original_text, answer_text)
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


@dataclass(frozen=True)
class RationalEquationResult:
    """Exact real solutions of one equation with the unknown in a denominator.

    `excluded` is carried beside the solutions because it is the whole
    difficulty of this shape. Clearing denominators produces an equation that
    is not the one that was asked: it is satisfied at values where the
    original is not even defined, and such a root verifies perfectly against
    the cleared form while being a wrong answer to the actual question.
    """

    variable: str
    solutions: tuple[str, ...]
    excluded: tuple[str, ...]
    classification: str

    @property
    def display_text(self) -> str:
        if not self.solutions:
            return self.classification
        return " or ".join(f"{self.variable} = {value}" for value in self.solutions)


def _denominators_of(expression: sympy.Expr, symbol: sympy.Symbol) -> list[sympy.Expr]:
    """Everything this expression divides by that involves the unknown.

    Read from the expression as written rather than from a single combined
    fraction. `together` and `cancel` are entitled to remove a common factor,
    and a cancelled factor is a restriction that has silently disappeared:
    `(x^2-4)/(x-2) = 0` cancels to `x+2 = 0`, which would offer two roots for
    a question that admits one, because the equation as asked is not defined
    at two at all.
    """
    found: list[sympy.Expr] = []
    for part in sympy.preorder_traversal(expression):
        if part.is_Pow and part.exp.is_negative and part.base.has(symbol):
            found.append(part.base)
    unique: list[sympy.Expr] = []
    for item in found:
        if not any(sympy.simplify(item - seen) == 0 for seen in unique):
            unique.append(item)
    return unique


def solve_rational_equation(
    expression: str, *, variable: str | None = None
) -> RationalEquationResult | None:
    """Solve an equation whose unknown appears in a denominator, over the reals.

    The polynomial solvers decline this shape by construction: `sympy.Poly`
    refuses an expression with its own generator raised to a negative power,
    which is exactly what `1/x` is. So the restrictions are collected from the
    equation as written, the equation is solved, and every candidate is then
    checked against both the restrictions and the original -- because the
    step that makes this solvable is the same step that makes it possible to
    produce an answer the question does not admit.

    Declines rather than guesses when a candidate is not real, when there are
    more solutions than the answer shapes carry, or when SymPy will not settle
    it: a rational equation this cannot answer belongs to whatever comes next,
    not to a plausible-looking result.
    """
    candidate = expression.strip().strip("$`").rstrip(".,;")
    if candidate.count("=") != 1:
        return None
    left_text, right_text = candidate.split("=", 1)
    try:
        left = _safe_sympy_expression(left_text)
        right = _safe_sympy_expression(right_text)
    except (SyntaxError, TypeError, ValueError, ZeroDivisionError):
        return None

    symbols = left.free_symbols | right.free_symbols
    if variable is None:
        if len(symbols) != 1:
            return None
        (symbol,) = symbols
    else:
        symbol = next((item for item in symbols if item.name == variable), None)
        if symbol is None or symbols != {symbol}:
            return None

    restrictions = _denominators_of(left, symbol) + _denominators_of(right, symbol)
    if not restrictions:
        # Nothing is divided by the unknown, so this is not the shape this
        # solver exists for. The polynomial paths own it.
        return None

    excluded: list[sympy.Expr] = []
    for denominator in restrictions:
        try:
            roots = sympy.solve(sympy.Eq(denominator, 0), symbol)
        except (NotImplementedError, TypeError, ValueError, ZeroDivisionError):
            return None
        for root in roots:
            # A denominator with no real zero restricts nothing over the reals.
            if root.is_real and not any(
                sympy.simplify(root - seen) == 0 for seen in excluded
            ):
                excluded.append(root)
    shown_exclusions = tuple(
        _display(value) for value in sorted(excluded, key=sympy.default_sort_key)
    )

    # True wherever it is defined at all. Still not true at the excluded
    # values, which is why they are reported rather than dropped.
    if sympy.simplify(left - right) == 0:
        return RationalEquationResult(
            symbol.name, (), shown_exclusions, "Infinite Solutions"
        )

    try:
        found = sympy.solve(sympy.Eq(left, right), symbol)
    except (NotImplementedError, TypeError, ValueError, ZeroDivisionError):
        return None
    if any(root.is_real is not True for root in found):
        return None
    if not found:
        # These symbols are real, so SymPy has already answered over the reals
        # and an equation with only complex roots comes back empty -- which is
        # indistinguishable here from one with no roots at all. They are not
        # the same answer: a lesson that has covered complex numbers wants the
        # roots, and "No Solution" would be confidently wrong. Ask again with
        # nothing assumed, and hand back anything that turns out to have them.
        unrestricted = sympy.Symbol(symbol.name)
        try:
            anywhere = sympy.solve(
                sympy.Eq(left, right).subs(symbol, unrestricted), unrestricted
            )
        except (NotImplementedError, TypeError, ValueError, ZeroDivisionError):
            return None
        if any(root.is_real is not True for root in anywhere):
            return None

    kept: list[sympy.Expr] = []
    for root in sorted(set(found), key=sympy.default_sort_key):
        if any(sympy.simplify(root - value) == 0 for value in excluded):
            continue  # introduced by clearing denominators; not a solution
        residual = sympy.simplify((left - right).subs(symbol, root))
        if residual == 0:
            kept.append(root)
    if len(kept) > 2:
        # One or two is what every answer shape here carries. More than that
        # is a question this cannot present, not one it should approximate.
        return None
    return RationalEquationResult(
        symbol.name,
        tuple(_display(root) for root in kept),
        shown_exclusions,
        {0: "No Solution", 1: "One Solution", 2: "Two Solutions"}[len(kept)],
    )


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
    # A question may name its variables one at a time instead. Lesson 1.5
    # question 7 -- the square root of -8x^9 under "Assume x > 0" -- matched no
    # phrase, so it was solved with no assumption, SymPy could not extract the
    # root, and the answer came back as `2sqrt(2(-x^9))`: unsimplified, missing
    # its `i`, and refused by the editor. Only claimed when every variable in
    # the expression is covered; an uncovered one leaves the assumption off,
    # which costs a decline rather than a wrong answer.
    named = _named_positive_variables(problem_text)
    if named and _candidate_variables(candidate) <= named:
        return True
    if operation not in {"simplify", "rationalize", "rational_exponents"}:
        return False
    if operation != "simplify":
        return True
    if not re.search(r"\\sqrt|\bsqrt\s*\(|[√∛∜]|\*\*\(1/", candidate):
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


def _named_positive_variables(problem_text: str) -> set[str]:
    """Variables the question declares positive one at a time.

    Hawkes writes "Assume x > 0" as readily as "assume all variables are
    positive", and only the phrase forms were recognised.
    """
    return {
        match.group(1)
        for match in re.finditer(r"\b([a-z])\s*(?:>|≥|>=)\s*0\b", problem_text.lower())
    }


#: Words in an expression that name a function or constant rather than a
#: variable, so a stray `t` from `sqrt` is not mistaken for one.
_NOT_VARIABLES = (
    "sqrt",
    "cbrt",
    "frac",
    "left",
    "right",
    "boxed",
    "cdot",
    "times",
    "log",
    "ln",
    "sin",
    "cos",
    "tan",
    "abs",
    "pi",
    "theta",
    "infty",
)


def _candidate_variables(candidate: str) -> set[str]:
    """The single letters in an expression that stand for variables."""
    text = re.sub(r"\\[a-zA-Z]+", " ", candidate)
    for word in _NOT_VARIABLES:
        text = re.sub(rf"\b{word}\b", " ", text, flags=re.IGNORECASE)
    return set(re.findall(r"[a-z]", text.lower()))


def _uses_imaginary_unit(problem_text: str, candidate: str, operation: str) -> bool:
    """Whether lowercase `i` denotes the imaginary unit in this question.

    Hawkes' complex-number lesson uses the generic prompt "Simplify the
    following expression", so the instruction alone carries no context. A
    numeric simplify expression whose only symbolic name is `i` and which
    either raises `i` to an integer power or combines conventional numeric
    complex-number literals is the narrow implicit form. Other variables or
    operations leave `i` as an ordinary real symbol.
    """
    variables = _candidate_variables(candidate)
    if "i" not in variables:
        return False
    if re.search(r"\b(?:complex|imaginary|powers?\s+of\s+i)\b", problem_text, re.I):
        return True
    if operation != "simplify" or variables != {"i"}:
        return False
    powers = re.finditer(
        r"(?<![A-Za-z])(?:i|\(\s*[+-]?\s*i\s*\))(?![A-Za-z])"
        r"\s*(?:\^|\*\*)\s*\{?\s*([+-]?\d+)",
        candidate,
    )
    if any(abs(int(match.group(1))) >= 2 for match in powers):
        return True
    return _has_numeric_complex_structure(candidate)


def _has_numeric_complex_structure(candidate: str) -> bool:
    """Recognize arithmetic written in the conventional ``a + bi`` form.

    Lesson 1.5's prompt does not say "complex"; the only context carried to
    the host is the expression itself. Two parenthesized numeric complex
    operands, or an integer power of one, are specific enough to distinguish
    the lesson's notation from a bare ordinary variable named ``i``. This is
    deliberately not a search for any occurrence of ``i``.
    """
    normalized = candidate.replace("−", "-").replace("–", "-")
    normalized = normalized.replace(r"\left", "").replace(r"\right", "")
    normalized = normalized.replace(r"\cdot", "*").replace("·", "*")
    normalized = re.sub(r"\s+", "", normalized)

    number = r"(?:\d+(?:\.\d*)?|\.\d+)"
    coefficient = rf"(?:{number}\*?)?"
    literal = (
        rf"\((?:[+-]?{number}[+-]{coefficient}i|"
        rf"[+-]?{coefficient}i[+-]{number})\)"
    )
    arithmetic = rf"{literal}(?:[+\-*/]?{literal})+"
    integer_power = rf"{literal}(?:\^|\*\*)\{{?[+-]?\d+\}}?"
    return re.fullmatch(rf"(?:{arithmetic}|{integer_power})", normalized) is not None


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
    if re.search(r"\\sqrt(?!\[)|\bsqrt\s*\(|√", candidate):
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
    # All three names, or an explicit classification verb. Counting mentions
    # was far too loose: "find the product of the binomial factors using the
    # appropriate special product (difference of two squares, square of a
    # binomial sum, or square of a binomial difference)" says "binomial" three
    # times and is a multiplication. It was answered `trinomial`, live.
    if re.search(r"\bclassif\w*\b", lowered) or all(
        re.search(rf"\b{name}\b", lowered)
        for name in ("monomial", "binomial", "trinomial")
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
    # Before the factoring checks, because "factor" is matched as a substring
    # and appears inside "binomial factors". "Find the product of the binomial
    # factors" is a multiplication; read as a factoring it declined, having
    # already been answered `trinomial` by a looser classification rule. A
    # named product beats an incidental noun.
    #
    # Before "simplify" too: these questions say "multiply the following
    # polynomials and simplify your answer" and mean multiply. Read the other
    # way round, `simplify` claimed the prompt and SymPy returned the
    # already-simple factored form -- the question's own input as its answer.
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
    # Narrower than factoring, and checked first. "Factor out the greatest
    # common factor" asks for one step; `sympy.factor` performs all of them and
    # answers a question that was not asked.
    if "greatest common factor" in lowered or re.search(r"\bgcf\b", lowered):
        return "gcf"
    if "factor" in lowered:
        return "factor"
    # Hawkes commonly says "Express your answer in simplified form" rather
    # than using the imperative "Simplify". They request the same exact
    # operation; missing the adjective sent a deterministic radical down the
    # slow fallback path and then reported it unsupported.
    #
    if re.search(r"\bsimplif(?:y|ied|ication)\b", lowered):
        return "simplify"
    # Lesson 1.5 question 5 says "Evaluate the following square root
    # expression" over √-27. That is an explicit radical evaluation, not a
    # polynomial substitution, and SymPy can answer it exactly. Do not broaden
    # this exception to bare "evaluate": without either a substitution above
    # or a named radical operation, the required evaluation data is absent.
    if re.search(r"\bevaluat\w*\b", lowered) and re.search(
        r"\b(?:radical|(?:square|cube|fourth)\s+root|root\s+expression)\b", lowered
    ):
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
    lowered = lowered.replace("−", "-").replace("–", "-")
    number = r"[+-]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:/[+-]?\d+(?:\.\d*)?)?)"
    match = re.search(
        rf"\b(?:for|when|at)\s+([a-z])\s*=\s*({number})(?![A-Za-z0-9_/]|\.\d)",
        lowered,
    )
    return (match.group(1), match.group(2)) if match else None


def _expression_candidates(problem_text: str, expressions: list[str]) -> list[str]:
    # `problem_text` selects the requested operation; it is not mathematical
    # input. Feeding its prose to the implicit-multiplication parser can turn
    # words into products of one-letter variables ("Simplify x + x" used to
    # become a large polynomial in S, i, m, ...). Only the separately extracted
    # and verified expression payload is eligible here.
    del problem_text
    candidates: list[str] = []
    for value in expressions:
        candidate = value.strip().strip("$`").rstrip(".,;")
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
    expression: str,
    *,
    positive_symbols: bool = False,
    imaginary_unit: bool = False,
) -> sympy.Expr:
    normalized = _python_expression(expression)
    tree = ast.parse(normalized, mode="eval")
    return _evaluate(
        tree.body,
        positive_symbols=positive_symbols,
        imaginary_unit=imaginary_unit,
    )


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
    # Protect the only accepted plain-text function while implicit
    # multiplication is inserted. Without this, `sqrt(9)` becomes
    # `s*q*r*t*(9)` and is confidently evaluated as a product of variables.
    sqrt_marker = "\N{SECTION SIGN}"
    if sqrt_marker in normalized:
        raise ValueError("expression contains unsupported characters")
    normalized = re.sub(r"sqrt(?=\()", sqrt_marker, normalized)
    normalized = re.sub(rf"(?<=[A-Za-z0-9)])(?={sqrt_marker})", "*", normalized)
    normalized = re.sub(rf"(?<=\))(?={sqrt_marker})", "*", normalized)
    normalized = re.sub(r"(?<=\d)(?=[A-Za-z(])", "*", normalized)
    normalized = re.sub(r"(?<=[A-Za-z)])(?=[A-Za-z\d(])", "*", normalized)
    normalized = normalized.replace(sqrt_marker, "sqrt")
    normalized = normalized.replace("^", "**")
    if not re.fullmatch(r"[A-Za-z0-9_+\-*/().]+", normalized):
        raise ValueError("expression contains unsupported characters")
    return normalized


def _evaluate(
    node: ast.AST,
    *,
    positive_symbols: bool = False,
    imaginary_unit: bool = False,
) -> sympy.Expr:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return sympy.Integer(node.value)
    if isinstance(node, ast.Constant) and isinstance(node.value, float):
        return sympy.Rational(Fraction(str(node.value)))
    if isinstance(node, ast.Name) and len(node.id) == 1 and node.id.isalpha():
        if imaginary_unit and node.id == "i":
            return sympy.I
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
        value = _evaluate(
            node.operand,
            positive_symbols=positive_symbols,
            imaginary_unit=imaginary_unit,
        )
        return value if isinstance(node.op, ast.UAdd) else -value
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "sqrt"
        and len(node.args) == 1
        and not node.keywords
    ):
        value = _evaluate(
            node.args[0],
            positive_symbols=positive_symbols,
            imaginary_unit=imaginary_unit,
        )
        return value ** sympy.Rational(1, 2)
    if isinstance(node, ast.BinOp):
        left = _evaluate(
            node.left,
            positive_symbols=positive_symbols,
            imaginary_unit=imaginary_unit,
        )
        right = _evaluate(
            node.right,
            positive_symbols=positive_symbols,
            imaginary_unit=imaginary_unit,
        )
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


def _split_half_integer_powers(expression: sympy.Expr) -> sympy.Expr:
    """`x**(9/2)` becomes `x**4 · √x`, so a radical answer reads as a radical.

    SymPy writes an extracted odd power as a half-integer exponent. The display
    path then had to render `x**(9/2)` with the radical machinery, and the
    factor reordering turned `2·√2·i·x**(9/2)` into `2ix√(2)^(9/2)` -- which is
    a different number, not a different spelling. Splitting the whole part off
    first also lets `_merge_square_roots` fold `√2·√x` into `√(2x)`, which is
    the simplest form these questions are marked against: lesson 1.5 question
    7, the square root of -8x^9 with x > 0, wants `2ix^4√(2x)`.

    Built with `evaluate=False` because SymPy would otherwise recombine the
    two factors into the exponent this exists to take apart.
    """
    factors = (
        list(expression.args) if isinstance(expression, sympy.Mul) else [expression]
    )
    split: list[sympy.Expr] = []
    changed = False
    for factor in factors:
        base, exponent = factor.as_base_exp()
        # `p // 2` floors, which is what a negative exponent needs too:
        # `x**(-3/2)` is `x**-2 · √x`.
        if exponent.is_Rational and exponent.q == 2 and abs(exponent.p) > 1:
            split.append(sympy.Pow(base, sympy.Integer(exponent.p // 2)))
            split.append(sympy.sqrt(base))
            changed = True
        else:
            split.append(factor)
    return sympy.Mul(*split, evaluate=False) if changed else expression


def _display(expression: sympy.Expr) -> str:
    numerator, denominator = expression.as_numer_denom()
    # Merged per part, never across the fraction bar: rebuilding the quotient
    # from merged parts lets SymPy pull a root back into the denominator,
    # undoing the merge.
    # Half-integer powers are split before merging, so `√2 · √x` can fold into
    # `√(2x)` rather than reaching the radical machinery as `x**(9/2)`.
    numerator = _merge_square_roots(_split_half_integer_powers(numerator))
    denominator = _merge_square_roots(_split_half_integer_powers(denominator))
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
    # SymPy writes the imaginary unit as `I`. Every question that asks for one
    # writes it `i`, and the editor publishes a character set containing the
    # lowercase letter and not the capital -- so `3I√3` is the right number in
    # the wrong alphabet, and `answerFitsEditor` refuses it before it can be
    # typed. Done before the radical rewriting below so the rest of this
    # function only ever sees the notation the answer is written in.
    value = re.sub(r"\bI\b", "i", value)
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
        merged.append(
            symbol if exponent == 1 else sympy.Pow(symbol, exponent, evaluate=False)
        )
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


def _same_expression_text(original: str, answer: str) -> bool:
    """Whether two displays differ only in mathematically empty typography.

    SymPy omits explicit multiplication and redundant outer parentheses. Those
    are display changes, not simplification: returning `xy` for `x*y`, or
    `x + 1` for `(x + 1)`, falsely claims that the requested work was done.
    """

    def cosmetic(value: str) -> str:
        value = _compact(value).replace(r"\cdot", "*").replace("**", "^")
        for _ in range(3):
            value = re.sub(r"\\sqrt\{([^{}]+)\}", r"sqrt(\1)", value)
            value = re.sub(r"√\(([^()]*)\)", r"sqrt(\1)", value)
            value = re.sub(r"√([A-Za-z0-9]+)", r"sqrt(\1)", value)
        value = value.replace("·", "*").replace("×", "*").replace("*", "")
        while value.startswith("(") and value.endswith(")"):
            depth = 0
            wraps_whole_value = True
            for index, character in enumerate(value):
                if character == "(":
                    depth += 1
                elif character == ")":
                    depth -= 1
                    if depth == 0 and index != len(value) - 1:
                        wraps_whole_value = False
                        break
            if not wraps_whole_value or depth != 0:
                break
            value = value[1:-1]
        return value

    return cosmetic(original) == cosmetic(answer)


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value)
