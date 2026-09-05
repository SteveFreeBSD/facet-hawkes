"""A word problem whose numbers are in a table, answered without a model.

Lesson 3.3 question 3 states three price/quantity/revenue rows, plots the same
three points, and asks which number of photos and which price per photo
maximize the revenue. Nothing on that page is an expression: there is no
function until one is fitted, so every route that reads MathJax has nothing to
read and the old regression route answers a question nobody asked -- it returns
the curve, not where the curve is highest.

The real Facet runs in-process here, so the route is genuinely decided on the
far side and a model that is never asked anything is proof that exact
mathematics answered. What these tests are mostly about is the second half: the
answer coming back is *proved here*, against the table this host read for
itself, before any of it is offered for insertion.
"""

from __future__ import annotations

import pytest
from facet_loopback import facet, reasoning

from ethnos.hawkes_host import asks_for_an_optimum, handle
from ethnos.hawkes_table import (
    TableUnreadable,
    agrees_with_plot,
    read_number,
    read_table,
)
from ethnos.hawkes_protocol import GraphPoint

#: The instruction as the add-on reads it off the page: the situation, then the
#: question. The table's own numbers are deliberately not in it.
#:
#: The sentence that decides everything -- the regression, the maximum, the
#: "as a function of", the rate per photo -- is the live wording, because every
#: one of those readings is keyed to it. The situation before it is written
#: fresh at the same length: it is coursework prose, it drives nothing, and its
#: only job here is to be long enough that the old 400-character cut fell
#: inside the sentence that follows.
INSTRUCTION = (
    "Step 1 of 1: A photographer sells prints at each of the first three shows "
    "she attends, charging a different price at every one of them. The price "
    "charged per photo at each show, along with the number of photos sold "
    "there and the total revenue it raised, appears in the table below. "
    "Treating revenue as a function of the number of photos sold, a graph of "
    "the three data points is also shown. If she uses quadratic regression to "
    "fit a curve to the data, what number of photos sold and what price per "
    "photo will maximize her revenue?"
)

COLUMNS = ["Price per Photo", "Number of Photos Sold", "Revenue"]
ROWS = [["$56", "4", "$224"], ["$52", "5", "$260"], ["$24", "12", "$288"]]

#: The same three measurements, as the scatter plots them.
PLOTTED = [{"x": "4", "y": "224"}, {"x": "5", "y": "260"}, {"x": "12", "y": "288"}]


def table_request(**changes) -> dict:
    problem = {
        "prompt_text": INSTRUCTION,
        "data_table": {"columns": COLUMNS, "rows": ROWS},
        "graph_points": PLOTTED,
        "answer_shape": {"kind": "multi", "count": 2},
    }
    problem.update(changes.pop("problem", {}))
    request = {
        "operation": "solve_hawkes_problem",
        "request_id": "table-1",
        "origin": "https://learn.hawkeslearning.com",
        "problem": problem,
    }
    request.update(changes)
    return request


def answering(monkeypatch):
    """A real Facet whose model, if it ever speaks, fails the test."""
    return facet(monkeypatch, **reasoning("FINAL ANSWER: a model answered this"))


# --- the answer -------------------------------------------------------------


def test_the_live_question_answers_nine_photos_at_thirty_six_dollars(monkeypatch):
    loopback = answering(monkeypatch)

    response = handle(table_request())

    assert response.status == "ready"
    # Two separate values, all the way to two separate boxes. Never one string
    # that something downstream would have to split.
    assert response.answer.parts == ["9", "36"]
    assert response.answer.keyboard_entry == ""
    assert loopback.prompts == [], "a model was asked to answer an exact question"


def test_the_answer_is_facet_exact_and_names_no_processor(monkeypatch):
    answering(monkeypatch)

    certainty = handle(table_request()).certainty

    assert certainty.source == "Facet Exact"
    assert certainty.answered_by == "facet"
    assert certainty.router == "solved"
    assert certainty.method == "SymPy exact least-squares regression"
    assert certainty.reading == "table"
    assert certainty.model is None
    assert certainty.actual_backend is None
    assert certainty.insertable is True


def test_the_panel_is_told_what_was_checked(monkeypatch):
    """Every claim on the card is one this host proved, not one it was given."""
    answering(monkeypatch)

    issues = handle(table_request()).certainty.issues

    assert (
        "3 rows read from the page's own table, 'Revenue' against 'Number of Photos Sold'"
        in issues
    )
    assert (
        "every row consistent: 'Price per Photo' x 'Number of Photos Sold' = 'Revenue'"
        in issues
    )
    assert "table agrees with the plotted points" in issues
    assert "Facet's fit satisfies the exact least-squares normal equations" in issues
    assert "maximum at 9 proved from the fit; value there 324" in issues
    assert "36 x 9 = 324 confirms the rate" in issues


def test_the_recognized_problem_shows_the_pair_of_columns_that_were_used(monkeypatch):
    answering(monkeypatch)

    text = handle(table_request()).problem_text

    assert "Revenue against Number of Photos Sold: (4,224), (5,260), (12,288)" in text


# --- what crosses to Facet --------------------------------------------------


def test_only_the_question_and_its_measurements_cross(monkeypatch):
    """No column headings, no table, no page. Facet gets the data and the words."""
    loopback = answering(monkeypatch)

    handle(table_request())

    crossed = loopback.problems[0]
    assert crossed["points"] == PLOTTED
    assert crossed["answer_parts"] == 2
    assert crossed["instruction"] == INSTRUCTION
    assert "result_kind" not in crossed, "this asks for a value, not a plan"
    assert set(crossed) <= {"instruction", "points", "answer_parts", "label"}


def test_no_expressions_are_invented_for_a_question_that_has_none(monkeypatch):
    loopback = answering(monkeypatch)

    handle(table_request())

    assert "expressions" not in loopback.problems[0]


# --- which route this question takes ----------------------------------------


def test_asking_for_the_curve_itself_still_takes_the_regression_route():
    """The two questions share a page shape and are not the same question."""
    assert asks_for_an_optimum(INSTRUCTION)
    assert not asks_for_an_optimum(
        "Use quadratic regression to find the quadratic function of best fit. "
        "Round the coefficients to three decimal places, if necessary."
    )


def test_a_question_asking_for_a_minimum_is_answered_as_a_minimum(monkeypatch):
    """The other end of the same capability, and its own sign check.

    A cost curve turns upwards, so the check that a maximise question's curve
    opens downwards has to be a check on the *question* rather than a constant.
    Written down as one, it refused every minimum ever asked.
    """
    answering(monkeypatch)
    asked = (
        "Treating cost as a function of the number of units made, if the plant "
        "uses quadratic regression to fit a curve to the data, what number of "
        "units made and what cost per unit will minimize her cost?"
    )
    # cost = 2n^2 - 12n + 32, which turns at three units, where cost is 14.
    upward = {
        "prompt_text": asked,
        "data_table": {
            "columns": ["Cost per Unit", "Number of Units Made", "Cost"],
            "rows": [["$22", "1", "$22"], ["$8", "2", "$16"], ["$4", "4", "$16"]],
        },
        "graph_points": [
            {"x": "1", "y": "22"},
            {"x": "2", "y": "16"},
            {"x": "4", "y": "16"},
        ],
    }

    response = handle(table_request(problem=upward))

    assert response.status == "ready"
    assert response.answer.parts == ["3", "14/3"]
    assert "minimum at 3 proved from the fit; value there 14" in (
        response.certainty.issues
    )


def test_a_reasoned_answer_is_refused_rather_than_inserted(monkeypatch):
    """There is an exact answer here, so a plausible one has nothing behind it.

    Facet is asked for a value; if the deterministic stage ever stopped owning
    this question, what came back would be a model's opinion with no working to
    check. That is refused, loudly, rather than typed into two answer boxes.
    """
    # A model that answers in exactly the shape the protocol requires, so
    # nothing but this host's own rule stands between it and two answer boxes.
    facet(monkeypatch, **reasoning("FINAL ANSWER: 3 and 3\nPART 1: 3\nPART 2: 3"))
    # A table whose fit opens upwards: the same question, with no maximum, so
    # the deterministic stage declines it and the reasoning route answers.
    upwards = {
        "data_table": {
            "columns": COLUMNS,
            "rows": [["$1", "1", "$1"], ["$2", "2", "$4"], ["$3", "3", "$9"]],
        },
        "graph_points": [
            {"x": "1", "y": "1"},
            {"x": "2", "y": "4"},
            {"x": "3", "y": "9"},
        ],
    }

    response = handle(table_request(problem=upwards))

    assert response.status == "unsupported"
    assert "reasoned one cannot be checked" in response.message


# --- the checks that refuse --------------------------------------------------


def test_a_table_that_disagrees_with_its_own_plot_is_refused(monkeypatch):
    """Two readings of the same numbers, from two pieces of markup.

    Both are exact and both are this host's, so a disagreement means one of the
    two readers is wrong -- and there is no way to tell which.
    """
    answering(monkeypatch)
    moved = [{"x": "4", "y": "225"}, *PLOTTED[1:]]

    response = handle(table_request(problem={"graph_points": moved}))

    assert response.status == "unsupported"
    assert "not the same data" in response.message


def test_a_table_whose_rows_do_not_multiply_out_is_refused(monkeypatch):
    answering(monkeypatch)
    wrong = [["$56", "4", "$225"], *ROWS[1:]]

    response = handle(
        table_request(problem={"data_table": {"columns": COLUMNS, "rows": wrong}})
    )

    assert response.status == "unsupported"
    assert "does not give 'Revenue' on row 1" in response.message


def test_a_question_naming_a_column_that_is_not_there_is_refused(monkeypatch):
    answering(monkeypatch)
    asked = INSTRUCTION.replace("Treating revenue", "Treating profit")

    response = handle(table_request(problem={"prompt_text": asked}))

    assert response.status == "unsupported"
    assert "names no column" in response.message


# --- the client's own boundary ----------------------------------------------


def test_a_value_question_must_be_about_one_thing():
    """Refused here, not over the transport, so a caller's mistake is local."""
    from ethnos.facet_client import FacetProtocolError, solve_math

    for wrong in (
        {"expressions": ["x^2"], "points": PLOTTED},
        {},
    ):
        with pytest.raises(FacetProtocolError, match="not both and not neither"):
            solve_math(instruction=INSTRUCTION, request_id="x", **wrong)


def test_a_parabola_plan_is_geometry_and_not_measurements():
    """Points beside a plan used to be dropped in silence.

    A plan is drawn from a function on a grid. Points are a different
    question's evidence, and sending them would have asked Facet something
    other than what the caller meant.
    """
    from ethnos.facet_client import FacetProtocolError, solve_math

    with pytest.raises(FacetProtocolError, match="geometry, not measurements"):
        solve_math(
            instruction="Graph the parabola.",
            request_id="x",
            result_kind="parabola_plan",
            expressions=["f(x)=(x-3)^2-1"],
            graph={"family": "parabola"},
            points=PLOTTED,
        )


# --- reading the table on its own -------------------------------------------


def test_currency_and_separators_are_presentation_not_value():
    assert read_number("$1,250") == 1250
    assert read_number(" 12 ") == 12
    assert read_number("5.5") * 2 == 11


def test_mathjax_leaves_invisible_operators_and_they_are_not_digits():
    """Found live, on lesson 3.3's next question.

    MathJax renders "$80" with an invisible-times between the parts, so a cell
    read off the page carries characters that show nothing. The add-on drops
    them and so does this, because the same page can reach here by more than
    one route and neither should refuse a number the page shows plainly.
    """
    assert read_number("$\u206280") == 80
    assert read_number("\u20621,250\u200b") == 1250


def test_a_cell_that_is_not_a_number_is_refused():
    with pytest.raises(TableUnreadable, match="not a plain number"):
        read_number("about 40")


def test_the_columns_come_from_the_question_not_from_their_order():
    """The same table, with the columns in a different order, reads the same."""
    swapped = ["Revenue", "Price per Photo", "Number of Photos Sold"]
    rows = [[row[2], row[0], row[1]] for row in ROWS]

    reading = read_table(swapped, rows, INSTRUCTION)

    assert reading.input_column == "Number of Photos Sold"
    assert reading.output_column == "Revenue"
    assert reading.points == (("4", "224"), ("5", "260"), ("12", "288"))


def test_a_non_numeric_third_column_is_a_label_and_not_a_rate():
    columns = ["Event", "Number of Photos Sold", "Revenue"]
    rows = [["Spring", "4", "224"], ["Summer", "5", "260"], ["Autumn", "12", "288"]]

    reading = read_table(columns, rows, INSTRUCTION)

    assert reading.rate_column == ""
    assert reading.points == (("4", "224"), ("5", "260"), ("12", "288"))


def test_a_repeated_input_is_refused():
    rows = [["$56", "4", "$224"], ["$52", "4", "$208"], ["$24", "12", "$288"]]

    with pytest.raises(TableUnreadable, match="repeats a value"):
        read_table(COLUMNS, rows, INSTRUCTION)


def test_a_question_that_never_says_what_it_is_a_function_of_is_refused():
    with pytest.raises(TableUnreadable, match="does not say what its curve"):
        read_table(COLUMNS, ROWS, "Use quadratic regression to maximize the revenue.")


def test_the_plot_check_compares_values_and_not_order():
    reading = read_table(COLUMNS, ROWS, INSTRUCTION)
    shuffled = [GraphPoint(**point) for point in reversed(PLOTTED)]

    agrees_with_plot(reading, shuffled)
