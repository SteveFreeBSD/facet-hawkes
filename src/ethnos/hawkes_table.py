"""Reading a question's data table as quantities, not as text.

A Hawkes word problem often states its numbers in a table with a heading over
each column. The add-on carries that table across exactly -- headings and cells,
as the page wrote them -- and this module turns it into the two things a
question about the data actually needs: which column the curve is a function
of, and the coordinates.

Everything here is a *reading*, and every reading is checked before it is used.
Which column is which comes from the question's own words ("treating revenue as
a function of the number of photos sold"), not from column order, because
column order is a fact about the page. A third column relating the two -- a
price per photo, a cost per unit -- is verified to multiply out on every row, so
a table that has been misread produces a refusal rather than a wrong answer
computed confidently from the wrong pair of columns.

Nothing in this module reaches Facet, and nothing in it knows what an element
is. It sits between the markup the add-on read and the question Ethnos asks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: A plain number as a table writes one: currency, thousands separators and a
#: trailing percent sign are presentation, and are removed before it is read.
PLAIN_NUMBER = re.compile(r"-?\d+(?:\.\d+)?\Z")

#: The question naming what its curve is a function of, and of what:
#: "Treating revenue as a function of the number of photos sold, ...". Both
#: names are then matched against the table's own headings.
FUNCTION_OF = re.compile(
    r"([A-Za-z][A-Za-z ]{0,40}?)\s+as\s+a\s+function\s+of\s+(?:the\s+)?"
    r"([A-Za-z][A-Za-z ]{0,60}?)\s*(?:[,.;]|\Z)",
    re.IGNORECASE | re.DOTALL,
)

#: Characters a page uses to join or separate parts of an expression without
#: showing anything: MathML's invisible operators, a zero-width space, and a
#: byte-order mark.
INVISIBLE = frozenset("\u2061\u2062\u2063\u2064\u200b\ufeff")

MIN_ROWS = 3


class TableUnreadable(ValueError):
    """The table, or the question about it, was not read confidently."""


@dataclass(frozen=True, slots=True)
class TableReading:
    """One table, read as the question asked for it to be read."""

    #: The heading of the column the curve is a function of, and of the one it
    #: gives. Reported so a reader can see which pair was used.
    input_column: str
    output_column: str
    #: The coordinates, exact, as decimal-free rational strings.
    points: tuple[tuple[str, str], ...]
    #: The heading of the column that relates the two, when there is one and it
    #: multiplies out on every row.
    rate_column: str = ""
    #: What was checked, in words, for whoever reads the panel afterwards.
    checks: tuple[str, ...] = ()


def read_number(cell: str):
    """One cell as an exact number, or refuse it.

    Returns a SymPy Rational, so `$56` is 56 and `5.5` is eleven halves rather
    than a float that is nearly eleven halves.
    """
    import sympy

    # Invisible operators are markup, not digits. MathJax leaves them between
    # the parts of a rendered expression, and a reading that let one through
    # here would refuse a number the page shows perfectly plainly.
    cleaned = "".join(character for character in cell if character not in INVISIBLE)
    cleaned = cleaned.replace("$", "").replace(",", "").replace("%", "").strip()
    if not PLAIN_NUMBER.fullmatch(cleaned):
        raise TableUnreadable(f"{cell!r} is not a plain number")
    return sympy.Rational(cleaned)


def _normalise(text: str) -> str:
    """A heading or a phrase, reduced to the words in it."""
    return " ".join(re.sub(r"[^A-Za-z0-9 ]", " ", text).lower().split())


def _one_column(columns: list[str], described: str, role: str) -> int:
    """The single column the question's own words name, or refuse.

    Matching is containment either way round, because a heading is usually a
    tidier spelling of the phrase ("Number of Photos Sold" for "the number of
    photos sold") and sometimes a shorter one ("Revenue" for "treating
    revenue"). Two matching columns is an ambiguity, and picking between them
    would decide the answer on nothing.
    """
    wanted = _normalise(described)
    found = [
        index
        for index, column in enumerate(columns)
        if _normalise(column)
        and (_normalise(column) in wanted or wanted in _normalise(column))
    ]
    if len(found) != 1:
        raise TableUnreadable(
            f"the question's {role}, {described!r}, names "
            f"{'no' if not found else str(len(found))} column of "
            f"{', '.join(repr(column) for column in columns)}"
        )
    return found[0]


def read_table(
    columns: list[str], rows: list[list[str]], instruction: str
) -> TableReading:
    """Read the table the way this question says to read it, or refuse.

    Raises `TableUnreadable` with the reason. A refusal here is the right
    outcome for anything ambiguous: what comes out of this function goes on to
    be typed into real answer boxes.
    """
    named = FUNCTION_OF.search(instruction)
    if named is None:
        raise TableUnreadable(
            "the question does not say what its curve is a function of"
        )
    output, given = named.group(1), named.group(2)
    y_index = _one_column(columns, output, "output")
    x_index = _one_column(columns, given, "input")
    if x_index == y_index:
        raise TableUnreadable(
            f"{columns[x_index]!r} was read as both the input and the output"
        )
    if len(rows) < MIN_ROWS:
        raise TableUnreadable(f"a regression needs at least {MIN_ROWS} rows")

    xs = [read_number(row[x_index]) for row in rows]
    ys = [read_number(row[y_index]) for row in rows]
    if len({*xs}) != len(xs):
        raise TableUnreadable(f"{columns[x_index]!r} repeats a value")

    checks = [
        f"{len(rows)} rows read from the page's own table, "
        f"{columns[y_index]!r} against {columns[x_index]!r}"
    ]
    rate_column = _checked_rate(columns, rows, x_index, y_index, xs, ys, checks)
    return TableReading(
        input_column=columns[x_index],
        output_column=columns[y_index],
        points=tuple((str(x), str(y)) for x, y in zip(xs, ys, strict=True)),
        rate_column=rate_column,
        checks=tuple(checks),
    )


def _checked_rate(columns, rows, x_index, y_index, xs, ys, checks) -> str:
    """Verify the third column relates the other two, when it is numeric.

    A three-column table of this shape states the same thing twice: a rate, a
    count, and their product. Multiplying it out on every row is a check on the
    *reading* -- it says the columns were paired up the way the page meant --
    and costs one multiplication. A column that is not numeric is a label, not
    a rate, and is left alone.
    """
    spare = [index for index in range(len(columns)) if index not in (x_index, y_index)]
    if len(spare) != 1:
        return ""
    index = spare[0]
    try:
        rates = [read_number(row[index]) for row in rows]
    except TableUnreadable:
        return ""  # a name, a date, an event: not a rate, and not a check
    wrong = [
        number
        for number, (rate, x, y) in enumerate(zip(rates, xs, ys, strict=True), start=1)
        if rate * x != y
    ]
    if wrong:
        raise TableUnreadable(
            f"{columns[index]!r} x {columns[x_index]!r} does not give "
            f"{columns[y_index]!r} on row {wrong[0]}"
        )
    checks.append(
        f"every row consistent: {columns[index]!r} x {columns[x_index]!r} "
        f"= {columns[y_index]!r}"
    )
    return columns[index]


def agrees_with_plot(reading: TableReading, plotted) -> None:
    """Refuse a table that disagrees with the graph of the same data.

    The page states these numbers twice -- once in the table, once as plotted
    points -- and the two readings are taken by completely different code from
    completely different markup. Requiring them to agree is the strongest check
    available here and costs nothing, so a misread table is caught before it
    becomes an answer rather than after.
    """
    drawn = sorted((point.x, point.y) for point in plotted)
    if drawn != sorted(reading.points):
        raise TableUnreadable(
            "the table and the plotted points are not the same data: "
            f"table {sorted(reading.points)}, plot {drawn}"
        )
