"""Why the companion declined, without carrying the question it declined.

`errorSolveRefused` was the whole of what the ring recorded, and it covers a
question Facet's solvers declined, a transport that failed, and a reply that
arrived shaped wrongly -- three faults fixed in three different places. Live on
6 September it stopped a diagnosis dead: the bundle could say only "the solver
was reached and declined this question".

Two things are now kept. `status`, which is a closed set in the protocol. And
the message up to its first colon, which is safe only because every
interpolation in the host happens after one -- so that is asserted here against
the host's own source, not assumed.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path


#: Stands in for an interpolation, so a message that begins with one cannot
#: accidentally look like a fixed string this test could match.
HOLE = "\x00"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOST = PROJECT_ROOT / "src" / "ethnos" / "hawkes_host.py"
PROTOCOL = PROJECT_ROOT / "src" / "ethnos" / "hawkes_protocol.py"
BACKGROUND = PROJECT_ROOT / "extension" / "background.js"


def _refusal_messages() -> list[str]:
    """Every message `error_response` is handed, as a matchable prefix.

    Interpolations become a placeholder rather than being dropped, so a message
    that begins with one cannot accidentally look like a fixed string.
    """
    tree = ast.parse(HOST.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and getattr(node.func, "id", "") == "error_response"
            and len(node.args) >= 2
        ):
            continue
        message = node.args[1]
        if isinstance(message, ast.Constant):
            found.append(str(message.value))
        elif isinstance(message, ast.JoinedStr):
            rendered = ""
            for part in message.values:
                rendered += str(part.value) if isinstance(part, ast.Constant) else HOLE
            found.append(rendered)
        else:  # pragma: no cover - a shape this test would need updating for
            found.append(f"<unreadable {ast.unparse(message)}>")
    return found


def _labels() -> list[tuple[str, str]]:
    """`REFUSAL_REASONS` as (label, pattern source) pairs, read from the file."""
    background = BACKGROUND.read_text(encoding="utf-8")
    block = background[background.index("const REFUSAL_REASONS") :]
    block = block[: block.index("]);")]
    return re.findall(r'\["([a-z-]+)",\s*/(.+?)/[gimsuy]*\]', block)


def _matches(pattern: str, message: str) -> bool:
    """The JavaScript patterns here are all plain enough for Python's engine.

    An interpolation stands in as a digit for matching, so a pattern that pins
    a count -- `Facet did not return the \\d+ separate answers` -- still lines
    up with the message it came from. Whether a message *begins* with an
    interpolation is decided before this, on the unsubstituted form.
    """
    return re.search(pattern, message.replace(HOLE, "1"), re.IGNORECASE) is not None


def test_every_refusal_the_host_can_send_has_a_label():
    """A new `error_response` in the host must not arrive as "unclassified"."""
    labels = _labels()
    unlabelled = [
        message
        for message in _refusal_messages()
        # One message is an exception's own class name and text, which has no
        # authored prefix at all; `host-exception` covers it and is asserted
        # against a real Python error below.
        if not message.startswith(HOLE)
        and not any(_matches(pattern, message) for _, pattern in labels)
    ]

    assert unlabelled == [], unlabelled


def test_the_only_prefixless_refusal_is_the_raised_exception():
    prefixless = [m for m in _refusal_messages() if m.startswith(HOLE)]

    assert prefixless == [f"{HOLE}: {HOLE}"]


def test_every_label_still_matches_something_the_host_sends():
    """And a refusal that has been reworded must not leave a dead label."""
    messages = _refusal_messages()
    dead = [
        label
        for label, pattern in _labels()
        if not any(_matches(pattern, message) for message in messages)
    ]

    # `host-exception` catches `f"{type(exc).__name__}: {exc}"`, whose rendered
    # form here is a placeholder rather than a real class name.
    assert dead == ["host-exception"], dead


def test_there_are_refusals_to_check():
    """Guards the sweeps above against silently passing on an empty list."""
    assert len(_refusal_messages()) >= 6
    assert len(_labels()) >= 10


def test_the_host_exception_label_matches_a_real_python_error():
    pattern = dict(_labels())["host-exception"]

    assert _matches(pattern, "ValueError: bad input")
    assert _matches(pattern, "KeyboardInterrupt: stopped")
    assert not _matches(pattern, "Facet did not answer: timeout")


def test_the_message_itself_is_never_written_to_the_ring():
    """The property that makes this safe.

    A decline reason can be `str(refusal)` from `facet_runtime.exact`, and a
    nested reason that interpolated before its own colon would put the question
    into a ring that promises never to hold it. Only a label authored in
    `background.js` is written.
    """
    background = BACKGROUND.read_text(encoding="utf-8")
    entry = background[background.index("runFacts.refusal = refusalReason") :][:400]

    assert "runFacts.refusal = refusalReason(message)" in entry
    assert "why: runFacts.refusal" in entry
    assert "message.slice" not in entry
    assert "message.split" not in entry
    # The label now outlives the ring as well: a retained failure record keeps
    # it so an offline triage can group refusals by kind. That makes "only a
    # label this file authored" a property of every assignment, not of one.
    assignments = re.findall(r"runFacts\.refusal\s*=\s*([^;\n]+)", background)
    assert assignments and all(
        value.strip() in {'""', "refusalReason(message)"} for value in assignments
    ), assignments
    assert "refusal: runFacts.refusal," in background
    # The full text still reaches the panel, which is not persisted.
    assert "detail: message" in background


def test_an_unknown_refusal_is_named_as_unknown_not_quoted():
    background = BACKGROUND.read_text(encoding="utf-8")
    reason = background[background.index("function refusalReason") :][:400]

    assert '"unclassified"' in reason
    assert "message" not in reason.split("return")[-1]


def test_the_status_the_browser_records_is_a_closed_set():
    protocol = PROTOCOL.read_text(encoding="utf-8")
    declared = re.search(r"status:\s*Literal\[([^\]]+)\]", protocol)

    assert declared is not None
    values = set(re.findall(r'"([a-z]+)"', declared.group(1)))
    assert values == {"ready", "ambiguous", "unsupported", "error", "ok"}


def test_the_refusal_is_still_reported_as_a_failure():
    """The log entry is additional, not a replacement: the panel must still be
    told, or a declined solve would look like one that never finished."""
    background = BACKGROUND.read_text(encoding="utf-8")
    block = background[background.index("async function acceptReply") :][:1800]

    assert 'log.warn("solve-refused"' in block
    assert 'fail("errorSolveRefused"' in block
    assert block.index('log.warn("solve-refused"') < block.index(
        'fail("errorSolveRefused"'
    )
