"""The multipart plain answer, written into the controls Hawkes owns.

Live, on 2026-09-10, lesson 1.6 asked for three consecutive integers and drew
three plain answer boxes for them -- `txt1_num`, `txt2_num`, `txt3_num`, one
enabled control apiece in `quant_wp_UI.controlsCollection`. The question was
read exactly, solved exactly, and routed to `hawkes-plain-fields`; the boxes
settled holding the three correct parts cumulatively and across each other,
and the writer's own read-back refused the insertion:

    transport  chosen=hawkes-plain-fields world=isolated
               writer=enterPlainAnswerParts editor_kind=multi
    FAILURE    answer-shape (errorInsertRejected)

That is the 2026-09-07 completion-table failure exactly, on a question with no
table in it, and for the same reason: the writer ran in the isolated world,
where `focus()` moves `document.activeElement` and Hawkes' own selection is
neither visible nor movable. `input` is delegated to the *selected* control,
so every part routed through whichever control the page had selected before
the panel was opened.

This file holds that surface to the invariant the table path already meets:

    logical part N -> the control Hawkes owns box N with -> write -> settle
    -> box N holds exactly part N and no other box moved -> only then advance

The page model is the one `test_hawkes_table_writer.py` built for the table --
a controlled editor with a buffer per control, a router the page moves and
DOM focus does not, and delegated `input` -- because it is the same editor.
"""

from __future__ import annotations

import json

import pytest

from test_hawkes_table_writer import PAGE, WRITER, quickjs

#: The live question's three boxes, in the order the mathematics numbers them,
#: which here is also the order the markup draws them.
LIVE_FIELDS = ["txt1_num", "txt2_num", "txt3_num"]
#: Three consecutive integers, as Facet proved them.
LIVE_PARTS = ["-7", "-6", "-5"]


def page(**options):
    """One multipart plain-answer question, drawn as the live page draws it."""
    context = quickjs.Context()
    context.eval(PAGE)
    context.eval(WRITER)
    context.eval(f"buildTable({json.dumps(LIVE_FIELDS)}, {json.dumps(options)});")
    return context


def score(parts):
    return {"score": {"offsets": [0] * len("".join(parts))}}


def write(context, parts=None, fields=None, writer="enterOwnedFields"):
    """Run one writer to completion and return what it reported."""
    parts = LIVE_PARTS if parts is None else parts
    fields = LIVE_FIELDS if fields is None else fields
    call = (
        f"enterOwnedFields({json.dumps(parts)}, {json.dumps(fields)}, "
        f"{json.dumps(score(parts))}, 'fields')"
        if writer == "enterOwnedFields"
        else f"{writer}({json.dumps(parts)}, {json.dumps(fields)})"
    )
    context.eval(f"globalThis.outcome = null; {call}.then(v => {{ outcome = v; }});")
    for _ in range(20000):
        if not context.execute_pending_job():
            break
    return json.loads(context.eval("JSON.stringify(outcome)"))


def boxesNow(context):
    """Each pinned box's *logical* value, by the id the page minted for it."""
    return dict(
        json.loads(
            context.eval(
                "JSON.stringify(fields.filter(f => f.kind === 'box').map(f => {"
                " const den = fields.find(o => o.kind === 'den'"
                "   && o.id === f.id.replace(/_num$/, '') + '_den' && o.visible);"
                " return [f.id, den ? f._value + '/' + den._value : f._value]; }))"
            )
        )
    )


def buffers(context):
    """What every page-owned control holds in its own model."""
    return json.loads(
        context.eval(
            "JSON.stringify(window.quant_wp_UI.controlsCollection"
            ".filter(c => c.buffer !== undefined && c.field.kind === 'box')"
            ".map(c => [c.field.id, c.buffer]))"
        )
    )


# --- the harness reproduces the live failure --------------------------------


def test_dom_focus_moves_neither_the_router_nor_the_mirror() -> None:
    """The fact the isolated writer could not see, on this surface too."""
    live = page()
    live.eval("document.getElementById('txt3_num').focus();")

    assert live.eval("document.activeElement.id") == "txt3_num"
    assert live.eval("window.quant_wp_UI.focusedElement.id") == "txt1_num"
    assert live.eval("window.quant_wp_UI.focusedElementIndex") == 0


def test_the_isolated_writer_crosses_every_plain_field() -> None:
    """The live run, reproduced: three writes reported, one control written.

    The page's selection sits on the first box, where it was left before the
    panel was opened, so all three parts route through that one control and
    each in turn rerenders that one box. What the DOM setter happens to leave
    in the other two is not what the page owns, and is not an answer.
    """
    live = page()

    reported = write(live, writer="oldWriter")

    assert reported["ok"] is True
    assert reported["placed"] == [1, 1, 1]
    # The page's own model holds one value, in the wrong place, three times
    # over -- and holds nothing at all for the two boxes that look filled in.
    assert buffers(live) == [["txt1_num", "-5"], ["txt2_num", ""], ["txt3_num", ""]]
    assert boxesNow(live)["txt1_num"] != LIVE_PARTS[0]


# --- the writer that replaced it --------------------------------------------


def test_every_part_settles_in_its_own_field() -> None:
    """The whole fix, against the page that broke the isolated writer."""
    live = page()

    reported = write(live)

    assert reported["ok"] is True
    assert reported["code"] == "entered-answer-fields"
    assert reported["fields"] == LIVE_FIELDS
    assert reported["settled"] == 3
    assert boxesNow(live) == dict(zip(LIVE_FIELDS, LIVE_PARTS))
    # And the page's own model agrees, which is the reading the DOM cannot
    # give and the one the whole failure turned on.
    assert buffers(live) == [list(pair) for pair in zip(LIVE_FIELDS, LIVE_PARTS)]
    assert reported["models"] == 3


def test_the_report_names_a_field_rather_than_a_blank() -> None:
    """One mechanism, two surfaces, and no table in this question's words."""
    live = page()

    reported = write(live)

    assert "cells" not in reported
    assert "blank" not in reported
    assert reported["ownership"] == ["cell"] * 3
    # The first box is where the page's own selection already was; the other
    # two were reached by running the focus handling a click would deliver.
    assert reported["selected"] == ["page", "focus", "focus"]


@pytest.mark.parametrize("focused", [0, 2, 4])
def test_each_field_is_selected_by_the_page_before_it_is_written(focused) -> None:
    """Wherever the page's own selection was left, it is moved to each box.

    The selection is proven from the mirror moving by itself, after the focus
    events a click delivers. Nothing here assigns it.
    """
    live = page(focused=focused)

    reported = write(live)

    assert reported["ok"] is True
    assert boxesNow(live) == dict(zip(LIVE_FIELDS, LIVE_PARTS))
    # Ending on the last box's own control: the caret is left in the answer.
    assert live.eval("window.quant_wp_UI.focusedElement.id") == "txt3_num"


def test_a_field_that_cannot_be_proven_selected_is_refused_unwritten() -> None:
    """A page that will not select is a refusal, not a smaller success."""
    # The page's selection left on the last box, as it is whenever the owner
    # was somewhere else before the panel was opened.
    live = page(focused=4)
    # Hawkes' own focus handling, taken away: `focus()` still moves
    # `document.activeElement`, and nothing moves the page's selection.
    live.eval("globalThis.__hawkesFocus = () => {};")

    reported = write(live)

    assert reported["ok"] is False
    assert reported["code"] == "answer-field-not-selected"
    assert reported["part"] == 1
    assert reported["written"] == 0
    assert boxesNow(live) == {id: "" for id in LIVE_FIELDS}


def test_a_page_that_crosses_two_fields_is_caught_and_put_back() -> None:
    """The failure this writer exists to catch, on this surface.

    Selection is correct throughout; the page writes the first box as well as
    the second every time the second is written. That is the editor putting an
    answer somewhere nobody asked for, and it is refused with the boxes as
    they were.
    """
    live = page()
    live.eval(
        "const one = window.quant_wp_UI.controlsCollection[controlFor('txt2_num')];"
        "Object.defineProperty(one, 'alsoRenders', {"
        "  value: document.getElementById('txt1_num'), enumerable: false});"
    )

    reported = write(live)

    assert reported["ok"] is False
    assert reported["code"] == "answer-field-crossed"
    assert reported["part"] == 2
    assert reported["moved"] == 1
    assert boxesNow(live) == {id: "" for id in LIVE_FIELDS}


def test_a_field_the_owner_has_already_typed_in_is_never_overwritten() -> None:
    """A blank is a position the page states; a solution box is somebody's work.

    The isolated writer refused a non-empty field before it wrote anything,
    and that rule is the surface's, not the writer's: a completion cell is
    cleared and typed into, and this is not one.
    """
    live = page()
    live.eval("document.getElementById('txt2_num').render('12');")

    reported = write(live)

    assert reported["ok"] is False
    assert reported["code"] == "answer-fields-not-empty"
    assert reported["part"] == 2
    assert boxesNow(live)["txt2_num"] == "12"
    assert boxesNow(live)["txt1_num"] == ""


def test_a_field_that_disappears_mid_answer_stops_the_write() -> None:
    """Hawkes swaps a question in place, and this now spans seconds."""
    live = page()
    live.eval(
        "const box = document.getElementById('txt3_num');"
        "const control = window.quant_wp_UI.controlsCollection[controlFor('txt2_num')];"
        "const rendered = control.field.render.bind(control.field);"
        "control.field.render = (text) => { rendered(text); box.isConnected = false; };"
    )

    reported = write(live)

    assert reported["ok"] is False
    assert reported["code"] == "answer-field-missing"
    assert reported["written"] in (1, 2)
    assert boxesNow(live)["txt1_num"] == ""


def test_the_shared_score_still_paces_one_note_per_character() -> None:
    """One clock across every box, as Answer Cadence states it."""
    live = page()

    reported = write(live)

    assert reported["timing"]["notes"] == len("".join(LIVE_PARTS))


def test_a_score_that_does_not_fit_the_answer_is_refused() -> None:
    live = page()

    context = live
    context.eval(
        "globalThis.outcome = null; enterOwnedFields("
        f"{json.dumps(LIVE_PARTS)}, {json.dumps(LIVE_FIELDS)}, "
        "{score: {offsets: [0]}}, 'fields').then(v => { outcome = v; });"
    )
    for _ in range(20000):
        if not context.execute_pending_job():
            break
    reported = json.loads(context.eval("JSON.stringify(outcome)"))

    assert reported == {"ok": False, "code": "answer-invalid"}


def test_an_unnamed_surface_is_refused_rather_than_guessed() -> None:
    live = page()

    context = live
    context.eval(
        "globalThis.outcome = null; enterOwnedFields("
        f"{json.dumps(LIVE_PARTS)}, {json.dumps(LIVE_FIELDS)}, "
        f"{json.dumps(score(LIVE_PARTS))}, 'boxes').then(v => {{ outcome = v; }});"
    )
    for _ in range(20000):
        if not context.execute_pending_job():
            break
    reported = json.loads(context.eval("JSON.stringify(outcome)"))

    assert reported == {"ok": False, "code": "answer-invalid"}
