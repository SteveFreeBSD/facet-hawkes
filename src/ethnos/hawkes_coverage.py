"""Which Hawkes questions the exact path answers, without a browser or a model.

Coverage is the add-on's real constraint, and it used to be discovered one live
failure at a time: meet an unhandled question, wait about seventy seconds for
the vision-plus-model fallback, and report it. One lesson produced three such
gaps in a single sitting.

Everything needed to find them is offline. Whether a question reaches an exact
solver is decided by `_requested_operation` reading a verb out of the prompt,
and whether that solver can then answer is decided by SymPy. Neither needs
Firefox, a screenshot, or Ollama -- so a whole lesson's worth of phrasings can
be swept in about a second.

The distinction this draws is the useful one:

`no-verb`
    The prompt matched no operation. A recognition gap: the host is handed
    "Solve the question in the image" and the question reaches a model with
    nothing stating what to do about it.
`solver-declined`
    An operation matched, and SymPy would not answer. A capability gap.

Both fall through to the model. They are fixed in completely different places,
and the fallback cannot tell you which one you have.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import time

from .answer_image import extract_final_math
from .symbolic_solver import _requested_operation, answer_symbolic_math


@dataclass(frozen=True)
class CoverageCase:
    """One question, phrased as the page states it."""

    id: str
    topic: str
    prompt: str
    expressions: list[str]
    #: The known-correct answer, where there is one. Optional: a case with no
    #: expected value still reports whether the exact path reached it at all,
    #: which is the coverage question.
    expected: str | None = None
    #: Whether declining is the correct outcome. Some prompts must not be
    #: answered exactly -- an ordering with two variables names no particular
    #: sequence. Without this the guards that make the solver safe would be
    #: reported as the gaps that make it incomplete.
    expects_decline: bool = False


@dataclass(frozen=True)
class CoverageResult:
    case: CoverageCase
    #: What `_requested_operation` selected, or None for a recognition gap.
    operation: str | None
    answer: str | None
    elapsed_ms: float
    verdict: str

    @property
    def covered(self) -> bool:
        return self.verdict == "exact"


#: Verdicts, worst first. `wrong` outranks the gaps deliberately: a confident
#: incorrect answer from the exact path is worse than falling through to a
#: model, because nothing downstream will question it.
VERDICTS = ("wrong", "no-verb", "solver-declined", "exact", "guarded")


def evaluate(case: CoverageCase) -> CoverageResult:
    """Run one case through the real selection and solving path."""
    operation = _requested_operation(case.prompt)
    started = time.perf_counter()
    result = answer_symbolic_math(
        problem_text=case.prompt, expressions=list(case.expressions)
    )
    elapsed_ms = (time.perf_counter() - started) * 1000

    if result is None:
        if case.expects_decline:
            return CoverageResult(case, operation, None, elapsed_ms, "guarded")
        verdict = "no-verb" if operation is None else "solver-declined"
        return CoverageResult(case, operation, None, elapsed_ms, verdict)

    answer = extract_final_math(result.raw_response)
    # A guard that answered is a failed guard, and it failed in the worst
    # direction: confidently, on a question it cannot actually settle.
    if case.expects_decline:
        return CoverageResult(case, operation, answer, elapsed_ms, "wrong")
    if case.expected is not None and _compact(answer) != _compact(case.expected):
        return CoverageResult(case, operation, answer, elapsed_ms, "wrong")
    return CoverageResult(case, operation, answer, elapsed_ms, "exact")


def _compact(text: str) -> str:
    """Compare answers without being fooled by spacing or a trailing period."""
    return "".join(text.split()).rstrip(".")


def sweep(cases: list[CoverageCase]) -> list[CoverageResult]:
    return [evaluate(case) for case in cases]


def load_cases(path: Path) -> list[CoverageCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "hawkes-coverage-v1":
        raise ValueError("not a hawkes-coverage-v1 corpus")
    return [
        CoverageCase(
            id=item["id"],
            topic=item["topic"],
            prompt=item["prompt"],
            expressions=list(item["expressions"]),
            expected=item.get("expected"),
            expects_decline=bool(item.get("expects_decline", False)),
        )
        for item in payload["cases"]
    ]


def summarize(results: list[CoverageResult]) -> dict[str, int]:
    counts = {verdict: 0 for verdict in VERDICTS}
    for result in results:
        counts[result.verdict] += 1
    return counts


def format_report(results: list[CoverageResult]) -> str:
    """A report that leads with what is not covered, because that is the point."""
    counts = summarize(results)
    total = len(results)
    covered = counts["exact"]
    guarded = counts["guarded"]
    lines = [
        f"{covered}/{total - guarded} answered exactly, "
        f"{guarded} correctly declined "
        f"({counts['wrong']} wrong, {counts['no-verb']} unrecognized, "
        f"{counts['solver-declined']} declined by the solver)",
    ]

    for verdict in VERDICTS:
        group = [r for r in results if r.verdict == verdict]
        if not group:
            continue
        lines.append("")
        lines.append(f"{_HEADINGS[verdict]} ({len(group)})")
        for result in sorted(group, key=lambda r: r.case.id):
            lines.append(f"  {result.case.id:<24} {result.case.topic}")
            lines.append(f"    {result.case.prompt}")
            if verdict == "wrong" and result.case.expects_decline:
                lines.append(f"    answered {result.answer!r}; should have declined")
            elif verdict == "wrong":
                lines.append(
                    f"    got {result.answer!r}, expected {result.case.expected!r}"
                )
            elif verdict == "solver-declined":
                lines.append(f"    matched {result.operation!r}, no answer")
            elif verdict == "exact":
                lines.append(f"    {result.answer}   [{result.elapsed_ms:.1f}ms]")
    return "\n".join(lines)


_HEADINGS = {
    "wrong": "WRONG -- the exact path answered, and answered incorrectly",
    "no-verb": "UNRECOGNIZED -- no verb matched, so the model is asked blind",
    "solver-declined": "DECLINED -- the operation matched, SymPy would not answer",
    "exact": "COVERED",
    "guarded": "GUARDED -- correctly declined rather than guessing",
}
