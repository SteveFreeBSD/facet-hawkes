"""Completion tables to read, generated rather than transcribed.

`tests/fixtures/table-completion.html` is one live page, and the values on it
are the ones Hawkes happened to publish on 2026-09-07. Hawkes changes them
every time, and moves the blanks with them: the same lesson can leave both
answers in the `y` row, or one in each, or four in one and one in the other.

So the shape is written here as a function of where the blanks are, and the
tests below drive it with many arrangements. Every page it builds carries the
live markup exactly: the row-headed grid with no `thead`, the accessibility
labels inside `QFractionBox`, and -- the part that matters most -- one hidden
answer control beside every visible box, which is what makes Hawkes' own
control collection twice the size of its answer surface.
"""

from __future__ import annotations

import random

#: A value cell, drawn by MathJax and stated in the MathML beside the glyphs.
VALUE = (
    '<td><mjx-container class="MathJax"><mjx-math aria-hidden="true">'
    "<mjx-mn>{value}</mjx-mn></mjx-math><mjx-assistive-mml><math>"
    "<mn>{value}</mn></math></mjx-assistive-mml></mjx-container></td>"
)

#: A blank cell: the visible box, and the hidden control Hawkes puts beside it.
BLANK = (
    '<td><span class="GridTable__Div_NoPad"><span class="FractionCell">'
    '<span class="FractionBoxStyle"><span class="QFractionBox">'
    '<label class="sr-only" for="{name}">answer baseline</label>'
    '<span><label class="sr-only" for="{name}_opt">answer control</label></span>'
    '<input class="qbaseCSS" id="{name}"{extra} maxlength="4">'
    '<input type="radio" class="opt" id="{name}_opt" hidden>'
    "</span></span></span></span></td>"
)

#: The same box without the page's accessibility labels. Used where a page is
#: deliberately malformed -- an unnamed box, two cells naming one box -- and
#: those labels, which point at an id, could not describe it either.
BARE = '<td><span class="QFractionBox"><input class="qbaseCSS" id="{name}"{extra} maxlength="4"></span></td>'

HEAD = (
    '<!doctype html><meta charset="utf-8">'
    '<div id="partInformation"><div class="part_status">Step 1 of 1:</div>'
    '<div id="partDescription">Complete the table of values below for the given '
    "equation. Write each answer as an integer."
    '<div><mjx-container class="MathJax"><mjx-math aria-hidden="true">'
    "<mjx-mi>x</mjx-mi><mjx-mo>=</mjx-mo><mjx-msup><mjx-mi>y</mjx-mi>"
    "<mjx-mn>2</mjx-mn></mjx-msup></mjx-math><mjx-assistive-mml><math><mi>x</mi>"
    "<mo>=</mo><msup><mi>y</mi><mn>2</mn></msup></math></mjx-assistive-mml>"
    "</mjx-container></div></div></div>"
)


def _cell(name, extras, bare) -> str:
    template = BARE if name in bare else BLANK
    return template.format(name=name, extra=extras.get(name, ""))


def row_headed_page(cells, ids, extras=None, bare=()) -> str:
    """A live-shaped row-headed grid.

    `cells` is one list per row -- the `x` row then the `y` row -- holding
    either a stated value or `None` for a blank. `ids` names the blanks in the
    order the *markup* writes them, which is row by row and is deliberately not
    the order the mathematics numbers them.
    """
    extras = extras or {}
    bare = set(bare)
    remaining = list(ids)
    rows = []
    for heading, row in zip("xy", cells):
        drawn = [f"<td>{heading}</td>"]
        for value in row:
            if value is None:
                drawn.append(_cell(remaining.pop(0), extras, bare))
            else:
                drawn.append(VALUE.format(value=value))
        rows.append(f"<tr>{''.join(drawn)}</tr>")
    return f"{HEAD}<table><tbody>{''.join(rows)}</tbody></table>"


def column_headed_page(columns, rows, ids, extras=None, bare=()) -> str:
    """The other shape: a heading row, then one record per row."""
    extras = extras or {}
    bare = set(bare)
    remaining = list(ids)
    head = "".join(f"<th>{name}</th>" for name in columns)
    drawn = []
    for row in rows:
        cells = []
        for value in row:
            if value is None:
                cells.append(_cell(remaining.pop(0), extras, bare))
            else:
                cells.append(VALUE.format(value=value))
        drawn.append(f"<tr>{''.join(cells)}</tr>")
    return (
        f"{HEAD}<table><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(drawn)}</tbody></table>"
    )


def random_grid(seed: int):
    """One randomized row-headed page, and what its blanks ought to map to.

    Returns the markup, and the ids in *semantic* blank order: pair by pair,
    `x` before `y` -- which is the order the reader numbers them and the order
    the host answers in.
    """
    rng = random.Random(seed)
    pairs = rng.randint(2, 5)
    positions = [(row, column) for column in range(pairs) for row in (0, 1)]
    blanks = rng.sample(positions, rng.randint(2, min(5, len(positions))))
    # Ids Hawkes' own numbering never makes contiguous, shuffled so nothing
    # downstream can recover the order by sorting or by arithmetic.
    names = [f"MatrixTextBoxes{number}_num" for number in rng.sample(range(0, 40), len(blanks))]

    cells = [[rng.randint(-99, 99) for _ in range(pairs)] for _ in range(2)]
    for row, column in blanks:
        cells[row][column] = None
    # Markup order: row by row, left to right.
    written = [
        (row, column)
        for row in (0, 1)
        for column in range(pairs)
        if (row, column) in blanks
    ]
    ids = dict(zip(written, names))
    # Semantic order: pair by pair, x before y.
    semantic = [
        ids[(row, column)]
        for column in range(pairs)
        for row in (0, 1)
        if (row, column) in blanks
    ]
    return row_headed_page(cells, [ids[position] for position in written]), semantic
