"""Why one answer would not go into one field, in shape only.

The multi-part path has reported the page's own editor rules since
`answer-parts-unplaceable`. The single-field path reported two reason codes and
a length, and live on lesson 3.3's "find the vertex" that left
`answer-needs-template` / `template-refused-by-question` standing for any of
fraction, radical, exponent or parentheses, against an unknown character set.
Diagnosing it needed a screenshot of the owner's coursework to reach a guess.

These tests pin what the report may say, and -- more importantly -- what it may
never say: the rejected characters are the answer, and the answer is never
written.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION = PROJECT_ROOT / "extension"


def _lift(source: str, name: str) -> str:
    """Lift one brace-balanced function out of `background.js`."""
    start = source.index(f"function {name}(")
    depth = 0
    for cursor in range(source.index("{", start), len(source)):
        if source[cursor] == "{":
            depth += 1
        elif source[cursor] == "}":
            depth -= 1
            if depth == 0:
                return source[start : cursor + 1]
    raise AssertionError(f"{name} is not brace-balanced")


@pytest.fixture(scope="module")
def describe():
    quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")
    background = (EXTENSION / "background.js").read_text(encoding="utf-8")
    context = quickjs.Context()
    context.eval(_lift(background, "describeFieldFailure"))

    def call(editor, fits, plan):
        return json.loads(
            context.eval(
                "JSON.stringify(describeFieldFailure("
                f'"unused", {json.dumps(editor)}, {json.dumps(fits)}, {json.dumps(plan)}))'
            )
        )

    return call


#: The live lesson 3.3 vertex control, as `hawkes-describe.js` read it.
VERTEX_EDITOR = {
    "ok": True,
    "kind": "dynamic",
    "enabled": True,
    "allowedCharacters": "0123456789-,",
    "maxLength": 16,
    "slots": {"base": "0123456789-,"},
    "templates": {
        "fraction": True,
        "radical": True,
        "exponent": True,
        "parentheses": False,
        "absoluteValue": False,
    },
}


def test_the_refused_template_is_named_not_merely_counted(describe):
    """`answer-needs-template` covered four different templates. Which one it
    was decided whether the page or the answer was at fault."""
    report = describe(
        VERTEX_EDITOR,
        {"insertable": False, "code": "answer-needs-template", "detail": "parentheses"},
        {"ok": False, "code": "template-refused-by-question", "detail": "parentheses"},
    )

    assert report["editorNeeds"] == "parentheses"
    assert report["planNeeds"] == "parentheses"
    assert report["templates"] == "fraction+radical+exponent"


def test_the_published_character_set_is_reported(describe):
    """Whether the box takes a comma is the difference between "the page
    supplies the parentheses" and "this answer does not belong here"."""
    report = describe(VERTEX_EDITOR, {"code": "answer-needs-template"}, {"ok": False})

    assert report["allowed"] == "0123456789-,"
    assert report["editorKind"] == "dynamic"
    assert report["editorEnabled"] is True
    assert report["editorMaxLength"] == 16
    assert report["hasSlots"] is True


def test_the_rejected_characters_are_counted_and_never_written(describe):
    """That detail is a fragment of the student's answer, so it is a count.

    `common/log.js` would redact a key named `detail`; this never builds one.
    """
    report = describe(
        {"ok": True, "kind": "dynamic", "allowedCharacters": "0123456789"},
        {
            "insertable": False,
            "code": "answer-has-rejected-characters",
            "detail": "x y",
        },
        {"ok": False, "code": "answer-has-rejected-characters", "detail": "x y"},
    )

    assert report["rejectedCount"] == 3  # "x", " ", "y"
    assert report["editorNeeds"] == ""
    assert report["planNeeds"] == ""
    # No value carries the characters themselves. Asserted over the values,
    # because "x" appears in the key `editorMaxLength` and a naive substring
    # check over the whole payload passes for the wrong reason.
    assert "x y" not in json.dumps(list(report.values()))


def test_an_unreadable_editor_still_produces_a_report(describe):
    report = describe(
        None, {"code": "editor-unknown"}, {"ok": False, "code": "editor-unknown"}
    )

    assert report["editorKind"] == "none"
    assert report["editorOk"] is False
    assert report["allowed"] == ""
    assert report["templates"] == ""


def test_a_very_long_character_set_is_bounded(describe):
    report = describe(
        {"ok": True, "kind": "dynamic", "allowedCharacters": "a" * 200},
        {"code": "answer-needs-template"},
        {"ok": False},
    )

    assert len(report["allowed"]) == 48


def test_the_single_field_report_carries_the_same_facts_as_the_multi_one():
    """The asymmetry that caused this: both paths must say what the page said
    about its own controls."""
    background = (EXTENSION / "background.js").read_text(encoding="utf-8")
    single = _lift(background, "describeFieldFailure")
    multi = _lift(background, "describePartsFailure")

    for fact in ("allowedCharacters", "templates", "maxLength", "kind", "enabled"):
        assert fact in single, fact
        assert fact in multi, fact
    # And it is only reached for the single-field case.
    assert "hasParts ? {} : describeFieldFailure(" in background
