"""What Facet can emit, and what this repository can enter.

Facet owns what an answer *is*. Hawkes Assistant owns how it is *entered*. Every
recurring defect in this project has been in neither half but in a composition
neither half named: `(1,-4)` was enterable and `17/2` was enterable and
`(17/2,-1/2)` was not, discovered live on coursework after Facet had been
answering it correctly for a day.

`answer.form` made the *family* visible on the wire. It is deliberately coarse:
four members, and growing it is a protocol change. That coarseness is why it
cannot be the whole gate. A new exact solver does not usually add a form -- it
adds a *notation* under an existing one, and `ordered-pair` already having a row
says nothing about whether `ordered-pair` carrying rationals can be typed.

So the unit here is the **composition**: the form, plus the structural features
of the value that decide which planning route it takes. `planEntry` branches on
exactly those features -- a bracketed pair, a top-level fraction, then a run of
templates for exponents, radicals, groups and absolute values -- so classifying
on them is classifying on the thing that actually determines whether an answer
can be entered.

`docs/answer-capabilities.json` is the authority: every composition, the page
topology it is entered into, the mechanism that does it, and whether it is
supported or explicitly not. `docs/ANSWER_CAPABILITIES.md` is rendered from it.
`tests/test_answer_compatibility.py` holds both against the real solvers and the
real planner.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUTHORITY = PROJECT_ROOT / "docs" / "answer-capabilities.json"

#: The closed vocabulary of structural features, and what each one costs to
#: enter. Every member is a branch `planEntry` actually takes; nothing is here
#: because it looked like a category.
NOTATION_FEATURES: dict[str, str] = {
    "plain": "digits, letters and signs only -- typed straight through",
    "fraction": "a division that must become a Fraction template or a slash step",
    "radical": "a root that must become a Radical or IndexedRadical template",
    "exponent": "a power that must become an Exponent template",
    "group": "parentheses that must come from a template, never typed",
    "absolute-value": "bars that must become an AbsoluteValue template",
    "comma": "several values in one box, separated the way the page asks",
    "interval": (
        "an interval's ends -- a bracket template chosen by the pair of marks, "
        "PBrace, SBrace, PSBrace or SPBrace -- and ∞, ∅ or ∪ typed where the "
        "box publishes them"
    ),
    "decimal": "a decimal point, typed only where the box publishes one",
    "phrase": "words rather than mathematics -- selected, or typed as text",
}

#: Ordered so a composition key reads the same however the features were found.
_FEATURE_ORDER = tuple(NOTATION_FEATURES)

_FRACTION = re.compile(r"\\frac|(?<![A-Za-z])/")
_RADICAL = re.compile(r"√|∛|∜|\\sqrt|\\?cbrt\s*\(|\bsqrt\s*\(")
_DECIMAL = re.compile(r"\d\.\d")
#: A square bracket closes an interval's end and is written in nothing else;
#: infinity, the empty set and a union are interval notation's own symbols. An
#: open finite interval, `(a,b)`, reads exactly as a pair does and takes the
#: same `PBrace` route, so it is not told apart here.
_INTERVAL = re.compile(r"[\[\]∞∅∪]")
_PHRASE = re.compile(r"\A[A-Za-z][A-Za-z ]*\Z")


def notation_of(value: str) -> tuple[str, ...]:
    """The structural features of one value, as the planner would meet them.

    Reads the *entry* text -- what the host would actually type -- rather than
    the display text. Those differ: a display `\\frac{-3 + √17}{2}` reaches the
    planner as `(-3+sqrt(17))/2`, and classifying the wrong one would declare a
    composition nothing ever enters.
    """
    if not isinstance(value, str) or value.strip() == "":
        return ()
    found: set[str] = set()
    if _PHRASE.fullmatch(value.strip()):
        found.add("phrase")
    else:
        if _FRACTION.search(value):
            found.add("fraction")
        if _RADICAL.search(value):
            found.add("radical")
        if "^" in value:
            found.add("exponent")
        if "|" in value:
            found.add("absolute-value")
        if "," in value:
            found.add("comma")
        if _DECIMAL.search(value):
            found.add("decimal")
        # Interval notation has no words in it. `No Solution (∅)` is a choice
        # glossing itself in set notation, selected rather than built.
        if _INTERVAL.search(value) and not re.search(r"[A-Za-z]{2}", value):
            found.add("interval")
        # A radical's own bracket is the radical's, not a group of its own.
        stripped = re.sub(r"(?:sqrt|cbrt)\s*\([^()]*\)", "", value)
        if "(" in stripped or "[" in stripped:
            found.add("group")
    if not found:
        found.add("plain")
    return tuple(feature for feature in _FEATURE_ORDER if feature in found)


def composition(form: str, notation: tuple[str, ...] | list[str]) -> str:
    """The key an entry is declared under: `ordered-pair/fraction+group`."""
    ordered = [feature for feature in _FEATURE_ORDER if feature in set(notation)]
    return f"{form}/{'+'.join(ordered)}" if ordered else form


def compositions_of(
    form: str, entry: str, parts: list[str] | tuple[str, ...]
) -> set[str]:
    """Every composition one answer presents.

    A multi-part answer is planned one part at a time, against its own control,
    so it presents one composition per part rather than an average of them.
    """
    values = list(parts) if parts else [entry]
    return {composition(form, notation_of(value)) for value in values if value}


@dataclass(frozen=True)
class Entry:
    """One declared composition, on one page topology."""

    id: str
    semantic: str
    form: str
    notation: tuple[str, ...]
    example: str
    editor: str
    topology: str
    mechanism: tuple[str, ...]
    status: str
    coverage: dict[str, str]
    probe: dict[str, Any] | None = None
    refusal: str = ""
    why: str = ""

    @property
    def composition(self) -> str:
        return composition(self.form, self.notation)

    @property
    def supported(self) -> bool:
        return self.status == "supported"


@dataclass(frozen=True)
class Authority:
    forms: tuple[str, ...]
    plan_kinds: tuple[str, ...]
    editors: dict[str, dict[str, Any]]
    entries: tuple[Entry, ...]

    def supported(self) -> tuple[Entry, ...]:
        return tuple(entry for entry in self.entries if entry.supported)

    def unsupported(self) -> tuple[Entry, ...]:
        return tuple(entry for entry in self.entries if not entry.supported)

    def declared_compositions(self) -> set[str]:
        return {entry.composition for entry in self.entries}

    def supported_compositions(self) -> set[str]:
        return {entry.composition for entry in self.entries if entry.supported}

    def editor_for(self, entry: Entry) -> dict[str, Any]:
        return self.editors[entry.editor]["description"]


def load(path: Path = AUTHORITY) -> Authority:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Authority(
        forms=tuple(raw["forms"]),
        plan_kinds=tuple(raw["plan_kinds"]),
        editors=raw["editors"],
        entries=tuple(
            Entry(
                id=item["id"],
                semantic=item["semantic"],
                form=item["form"],
                notation=tuple(item["notation"]),
                example=item["example"],
                editor=item["editor"],
                topology=item["topology"],
                mechanism=tuple(item["mechanism"]),
                status=item["status"],
                coverage=item["coverage"],
                probe=item.get("probe"),
                refusal=item.get("refusal", ""),
                why=item.get("why", ""),
            )
            for item in raw["entries"]
        ),
    )
