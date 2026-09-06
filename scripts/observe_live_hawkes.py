#!/usr/bin/env python3
"""One correlated look at the live Hawkes session, for the agent after this one.

Every live sweep so far has ended the same way: the evidence existed, in six
places, and correlating it was the work. A screenshot said what was on screen;
the diagnostic ring said what the add-on thought; `git status` said what the
tree held; `about:debugging` said nothing at all about which build was loaded;
and the timestamps came from three different clocks. Twice the conclusion was
wrong because a temporary add-on was running code the tree no longer contained,
and the fix under test had never been loaded at all.

This gathers those into one bundle, from one clock reference, keyed by run.

    python3 scripts/observe_live_hawkes.py
    python3 scripts/observe_live_hawkes.py --bundle --screenshot --match hawkes
    python3 scripts/observe_live_hawkes.py --run r2f8xk91c4 --json

What it does *not* do is as much the point. It reads: the profile database on
a throwaway copy, the two working trees, `/proc`, KWin's window list, and
Ollama's local HTTP endpoint. It never launches Firefox, never connects to the
add-on, never sends the page a keystroke or a click, and never asks the event
page for anything -- so an event page Firefox has unloaded stays unloaded, and
nothing observed here is observation-induced. `--screenshot` is the one thing
that touches the desktop at all: it borrows focus for the capture and hands it
straight back, through `inspect_live_firefox`.

Screenshots of a Hawkes page are the owner's coursework. They are written 0600
into a bundle directory whose deletion command this prints, and they are the
only part of a bundle that carries page content.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS.parent
EXTENSION_DIR = PROJECT_ROOT / "extension"
RUNTIME_ROOT = PROJECT_ROOT.parent / "facet-runtime"

#: Everything this tool may run. Asserted by a test, because the value of a
#: read-only observer is entirely in the "read-only" part: an inspection that
#: could press a button would have to be reasoned about before every use.
ALLOWED_COMMANDS = frozenset({"git", "qdbus6", "journalctl", "spectacle"})

OLLAMA_ROOT = "http://127.0.0.1:11434"
OLLAMA_TIMEOUT = 1.5


class ObservationError(RuntimeError):
    """A prerequisite for a safe observation was not satisfied."""


def _load(name: str):
    """Import a sibling script as a module, rather than re-implementing it."""
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    if spec is None or spec.loader is None:  # pragma: no cover - packaging fault
        raise ObservationError(f"cannot load {name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- the clock -------------------------------------------------------------


def clock(reference: float | None = None) -> dict:
    """Local and UTC from one reading, so two records cannot disagree.

    Correlating a screenshot filename, a log entry and a shell prompt has meant
    reading three clocks and one unstated timezone. Everything below stamps
    itself from this single value.
    """
    now = time.time() if reference is None else reference
    utc = datetime.fromtimestamp(now, timezone.utc)
    local = datetime.fromtimestamp(now).astimezone()
    return {
        "record": "clock",
        "epoch_ms": round(now * 1000),
        "utc": utc.isoformat(timespec="milliseconds"),
        "local": local.isoformat(timespec="milliseconds"),
        "timezone": local.tzname(),
        "utc_offset_minutes": round(local.utcoffset().total_seconds() / 60),
    }


def _stamp(epoch_ms, reference: dict) -> dict | None:
    """One log timestamp in both zones, using the observation's own offset."""
    if not isinstance(epoch_ms, (int, float)):
        return None
    seconds = epoch_ms / 1000
    return {
        "epoch_ms": round(epoch_ms),
        "utc": datetime.fromtimestamp(seconds, timezone.utc).isoformat(
            timespec="milliseconds"
        ),
        "local": datetime.fromtimestamp(seconds).astimezone().isoformat(
            timespec="milliseconds"
        ),
        "ago_seconds": round(reference["epoch_ms"] / 1000 - seconds, 1),
    }


# --- the two working trees -------------------------------------------------


def _git(root: Path, *args: str) -> str | None:
    if not (root / ".git").exists():
        return None
    try:
        done = subprocess.run(
            ["git", "-C", str(root), *args],
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def repository(root: Path) -> dict:
    """HEAD, subject, and what is uncommitted. Both repos, one shape."""
    if not root.is_dir():
        return {"path": str(root), "present": False}
    status = _git(root, "status", "--porcelain")
    dirty = [line for line in (status or "").splitlines() if line.strip()]
    return {
        "path": str(root),
        "present": True,
        "head": _git(root, "rev-parse", "HEAD"),
        "short": _git(root, "rev-parse", "--short", "HEAD"),
        "branch": _git(root, "rev-parse", "--abbrev-ref", "HEAD"),
        "subject": _git(root, "log", "-1", "--format=%s"),
        "committed": _git(root, "log", "-1", "--format=%cI"),
        "dirty": bool(dirty),
        "dirty_files": [line[3:] for line in dirty[:40]],
        "dirty_count": len(dirty),
    }


# --- what code Firefox is running -----------------------------------------


MARKED_PART = re.compile(r'^\s*"([^"]+)":\s*([^,\n]+),\s*$', re.MULTILINE)
IMPORT_LINE = re.compile(r"^import\s[\s\S]*?;\s*$", re.MULTILINE)
IMPORT_FROM = re.compile(r'^import\s[\s\S]*?from\s+"([^"]+)";', re.MULTILINE)

QUICKJS_PRELUDE = """
globalThis.console = { log(){}, warn(){}, error(){}, info(){}, debug(){} };
globalThis.setTimeout = () => 1;
globalThis.clearTimeout = () => {};
globalThis.setInterval = () => 1;
globalThis.clearInterval = () => {};
globalThis.self = { addEventListener(){} };
globalThis.window = undefined;
globalThis.browser = {
  runtime: { getManifest: () => ({ version: "0" }), getURL: (p) => p,
             onConnect: { addListener(){} }, onSuspend: { addListener(){} } },
  storage: { local: { get: () => Promise.resolve({}), set: () => Promise.resolve(),
                      remove: () => Promise.resolve() },
             session: { get: () => Promise.resolve({}), set: () => Promise.resolve(),
                        remove: () => Promise.resolve() },
             onChanged: { addListener(){} } },
  i18n: { getMessage: (name) => name },
};
globalThis.AudioContext = function () {};
globalThis.OfflineAudioContext = function () {};
"""


def _marked_parts(background: str) -> list[tuple[str, str]]:
    """The marker's own definition, read out of `markedCode()` in background.js.

    Parsed rather than restated. A second copy of that list here would be one
    more thing to keep in step, and the failure it would produce -- a marker
    that never matches -- looks exactly like the stale build it exists to
    detect.
    """
    start = background.find("function markedCode()")
    if start < 0:
        return []
    end = background.find("\n}", start)
    return MARKED_PART.findall(background[start : end if end > 0 else len(background)])


def _balance(source: str, start: int, opening: str, closing: str) -> int:
    """Index just past the delimiter that closes the one at `start`.

    String, template and comment contents are skipped, so a brace or a
    parenthesis inside any of them cannot close the construct early.
    """
    depth, position, length = 0, start, len(source)
    while position < length:
        char = source[position]
        if char in "\"'`":
            quote, position = char, position + 1
            while position < length and source[position] != quote:
                position += 2 if source[position] == "\\" else 1
            position += 1
            continue
        if char == "/" and position + 1 < length and source[position + 1] == "/":
            newline = source.find("\n", position)
            if newline < 0:
                break
            position = newline
            continue
        if char == "/" and position + 1 < length and source[position + 1] == "*":
            position = source.find("*/", position) + 2
            continue
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return position + 1
        position += 1
    return -1


def _function_source(source: str, name: str) -> str | None:
    """The exact text `Function.prototype.toString()` would return.

    Top-level declarations only. The parameter list is balanced before the body
    is looked for, because a default value is an expression: `askEthnos(
    operation, extra = {}, ...)` opens and closes a brace before the body ever
    starts, and matching from the first brace found returned forty-six
    characters of a two-thousand-character function -- silently, as a marker
    that simply never matched the browser's.
    """
    match = re.search(rf"^(?:async\s+)?function\s+{re.escape(name)}\s*\(", source, re.M)
    if not match:
        return None
    after_parameters = _balance(source, match.end() - 1, "(", ")")
    if after_parameters < 0:
        return None
    body = source.find("{", after_parameters)
    if body < 0:
        return None
    closed = _balance(source, body, "{", "}")
    return None if closed < 0 else source[match.start() : closed]


def _module_order(names: list[str]) -> list[str]:
    """Modules before the modules that import them."""
    ordered: list[str] = []
    seen: set[str] = set()

    def visit(name: str) -> None:
        if name in seen or not (EXTENSION_DIR / name).is_file():
            return
        seen.add(name)
        source = (EXTENSION_DIR / name).read_text(encoding="utf-8")
        for target in IMPORT_FROM.findall(source):
            visit(target.lstrip("/"))
        ordered.append(name)

    for name in names:
        visit(name)
    return ordered


def working_tree_marker() -> dict:
    """Recompute the running build's marker from the tree, the same way.

    The add-on folds the source text of what it loaded; this folds the source
    text of what is on disk, using the add-on's own `collectSources` for the
    module halves so the two cannot drift apart in the interesting direction.
    Comparing the results is the whole answer to "is Firefox running this?".
    """
    background_path = EXTENSION_DIR / "background.js"
    marker_path = EXTENSION_DIR / "common" / "build-marker.js"
    if not background_path.is_file() or not marker_path.is_file():
        return {"computed": False, "why": "no build marker in this tree"}
    try:
        import quickjs
    except ImportError:
        return {"computed": False, "why": "quickjs is not installed in this environment"}

    background = background_path.read_text(encoding="utf-8")
    parts = _marked_parts(background)
    if not parts:
        return {"computed": False, "why": "markedCode() could not be read"}

    module_parts = [(name, expr) for name, expr in parts if not name.startswith("background.js")]
    own_parts = [(name, expr) for name, expr in parts if name.startswith("background.js")]

    modules = sorted({name.split("#", 1)[0] for name, _ in module_parts if "/" in name})
    context = quickjs.Context()
    context.eval(QUICKJS_PRELUDE)
    try:
        for name in _module_order([*modules, "common/build-marker.js"]):
            source = (EXTENSION_DIR / name).read_text(encoding="utf-8")
            context.eval(IMPORT_LINE.sub("", source).replace("export ", ""))
        literal = ", ".join(f"{json.dumps(name)}: {expr}" for name, expr in module_parts)
        collected = json.loads(
            context.eval(f"JSON.stringify(collectSources({{{literal}}}))")
        )
    except Exception as error:  # noqa: BLE001 - any failure means "cannot say"
        return {"computed": False, "why": f"modules did not evaluate: {error}"}

    entries = [(name, text) for name, text in collected]
    missing = []
    for name, expr in own_parts:
        text = _function_source(background, expr.strip())
        if text is None:
            missing.append(expr.strip())
            continue
        entries.append((name, text))

    return {
        "computed": True,
        **fold(entries),
        "unresolved": missing,
    }


def fold(entries: list[tuple[str, str]]) -> dict:
    """`common/build-marker.js`'s fold, in Python. The two must agree exactly."""
    lines = sorted(
        f"{symbol} {hashlib.sha256(text.encode('utf-8')).hexdigest()}"
        for symbol, text in entries
    )
    digest = hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()
    return {
        "marker": digest[:12],
        "symbols": len(entries),
        "chars": sum(len(text) for _, text in entries),
    }


def touched_after(when_ms: float | None) -> list[str]:
    """Extension files modified after the running event page started.

    A file newer than the load is a file whose current content Firefox has not
    read. This is the check that catches the case the marker cannot: a tree
    that changed since the add-on was last reloaded.
    """
    if not when_ms:
        return []
    cutoff = when_ms / 1000
    changed = []
    for path in sorted(EXTENSION_DIR.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.suffix not in {".js", ".json", ".html", ".css"}:
            continue
        if path.stat().st_mtime > cutoff:
            changed.append(_relative(path))
    return changed


def _relative(path: Path) -> str:
    """Project-relative where that reads better, absolute where it must."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


# --- runs, reconstructed from the ring -------------------------------------

#: Events that begin one user operation, for a log written before run ids
#: existed. Adjacency is a guess and is labelled as one.
RUN_OPENERS = ("solve-started", "answer-target-inspected", "panel-window-changed")

#: Events that end one. A second opener after one of these is a second run; a
#: second opener before one is the same run still getting ready -- which is
#: what a prepare followed by a solve looks like, and splitting those in two
#: was reporting every solve as a run with no question and no editor.
RUN_CLOSERS = frozenset({"solved", "inserted", "failed", "graph-plan-validated"})

#: Silence longer than this ends an uncorrelated run. Nothing the add-on does
#: takes five minutes; a gap that long is the owner having gone away, and
#: without this rule one adjacency group spanned six hours of it and reported
#: itself as a single operation lasting `+21989128ms`.
RUN_GAP_MS = 5 * 60 * 1000

#: Ordered failure rules. First match wins; each says what it saw, so a verdict
#: can be argued with rather than believed.
FAILURE_RULES = (
    (
        "lifecycle",
        lambda run: len(run["generations"]) > 1,
        "the event page turned over mid-run: state and any in-flight work were lost",
    ),
    (
        "lifecycle",
        lambda run: run["error_key"] in {"errorTabMoved", "errorInsertionAbandoned"}
        or "insertion-target-changed" in run["events_seen"],
        "the target moved between pinning and writing",
    ),
    (
        "safety",
        lambda run: run["error_key"]
        in {"errorQuestionChanged", "errorAnswerChanged", "errorQuestionUnverified"},
        "a guard refused to write: the question or the answer was no longer the one reviewed",
    ),
    (
        "browser",
        lambda run: run["error_key"]
        in {
            "errorNoTab",
            "errorWrongSite",
            "errorTabAccessLost",
            "errorFrameUnreachable",
            "errorFrameUnreachableAt",
            "errorFrameAmbiguous",
            "errorNoFocusedField",
            "errorEditorDialogOpen",
            "errorNoBridge",
        },
        "the add-on could not reach the page, the frame or the field",
    ),
    (
        "evidence",
        lambda run: run["error_key"] in {"errorNoCapture", "errorQuestionRegion"}
        or (run["error_key"] == "errorSolveRefused" and run["evidence_refused"]),
        "the question could not be read exactly and the picture path did not rescue it",
    ),
    (
        "evidence",
        lambda run: run["error_key"] == "errorTranscriptionDisputed",
        "two readings of the picture disagreed",
    ),
    (
        "runtime",
        lambda run: run["error_key"] in {"errorEthnosUnreachable", "errorEthnosVersion"}
        or "health-failed" in run["events_seen"],
        "the native companion did not answer",
    ),
    (
        "timing",
        lambda run: run["error_key"] in {"errorEthnosTimeout", "errorOperationTimeout"},
        "the work did not finish inside its deadline",
    ),
    (
        "capability",
        lambda run: run["error_key"] == "errorSolveRefused",
        "the solver was reached and declined this question",
    ),
    (
        "answer-shape",
        lambda run: run["error_key"]
        in {
            "errorAnswerInvalid",
            "errorAnswerNeedsTemplate",
            "errorAnswerNeedsAbsoluteValue",
            "errorTemplateRefused",
            "errorOptionAnswer",
            "errorAnswerRejected",
            "errorUnsupportedField",
            "errorFieldNotEditable",
            "errorEditorUnknown",
            "errorInsertRejected",
        }
        or "answer-not-insertable" in run["events_seen"]
        or "answer-parts-unplaceable" in run["events_seen"],
        "an answer was produced that this editor will not take",
    ),
)


def _data(entry: dict) -> dict:
    value = entry.get("data")
    return value if isinstance(value, dict) else {}


def group_runs(entries: list[dict]) -> list[dict]:
    """Split the ring into user operations.

    A build that stamps run ids is grouped by them exactly. An older one is
    segmented on the events that open an operation, and every run it produces
    is marked `correlated: false` -- because adjacency is a guess, and a guess
    presented as a fact is how two solves in two windows became one story.
    """
    groups: list[dict] = []
    by_run: dict[str, dict] = {}
    for entry in entries:
        run_id = entry.get("run")
        if run_id:
            group = by_run.get(run_id)
            if group is None:
                group = {"run": run_id, "correlated": True, "entries": []}
                by_run[run_id] = group
                groups.append(group)
            group["entries"].append(entry)
            continue
        event = entry.get("event")
        current = groups[-1] if groups else None
        settled = current is not None and any(
            seen.get("event") in RUN_CLOSERS for seen in current["entries"]
        )
        repeated = (
            current is not None
            and event == "solve-started"
            and any(seen.get("event") == "solve-started" for seen in current["entries"])
        )
        idle = (
            current is not None
            and current["entries"]
            and (entry.get("t", 0) or 0) - (current["entries"][-1].get("t", 0) or 0)
            > RUN_GAP_MS
        )
        if (
            current is None
            or current["correlated"]
            or idle
            or (event in RUN_OPENERS and (settled or repeated))
        ):
            groups.append(
                {"run": f"~adjacent-{len(groups) + 1}", "correlated": False, "entries": []}
            )
        groups[-1]["entries"].append(entry)
    return [group for group in groups if group["entries"]]


def summarize_run(group: dict, reference: dict) -> dict:
    """One operation, as much of it as the ring recorded."""
    entries = group["entries"]
    seen = {entry.get("event") for entry in entries}
    first, last = entries[0], entries[-1]

    run = {
        "record": "run",
        "run": group["run"],
        "correlated": group["correlated"],
        "generations": sorted({e["gen"] for e in entries if e.get("gen")}),
        "started": _stamp(first.get("t"), reference),
        "ended": _stamp(last.get("t"), reference),
        "elapsed_ms": round((last.get("t", 0) or 0) - (first.get("t", 0) or 0)),
        "scopes": sorted({str(e.get("scope", "")) for e in entries if e.get("scope")}),
        "events_seen": seen,
        "entries": len(entries),
        "signature": None,
        "target": None,
        "question": None,
        "editor": None,
        "stages": [],
        "route": None,
        "runtime": None,
        "ownership": None,
        "cadence": None,
        "answer_length": None,
        "outcome": "incomplete",
        "error_key": "",
        "evidence_refused": "evidence-refused" in seen,
    }

    for entry in entries:
        event, data = entry.get("event"), _data(entry)
        if event == "question-identified":
            run["signature"] = data.get("signature")
        elif event == "evidence-refused":
            run["question"] = {
                "read": "refused",
                "expressions": data.get("expressions"),
                "graph": data.get("graph"),
                "table": data.get("table"),
                "prompt_chars": data.get("promptChars"),
            }
        elif event == "question-read" and run["question"] is None:
            run["question"] = {"read": "markup", "expressions": data.get("expressions")}
        elif event == "answer-target-inspected":
            run["editor"] = {
                "code": data.get("code"),
                "via": data.get("via"),
                "fields": data.get("fields"),
                "multi_field_evidence": data.get("multiFieldEvidence"),
            }
            if data.get("tabId") is not None:
                run["target"] = {
                    "window": data.get("windowId"),
                    "tab": data.get("tabId"),
                    "frame": data.get("frameId"),
                    "frames_probed": data.get("frames"),
                }
        elif event in {"editor-described", "multi-editor-described"}:
            run["editor"] = {**(run["editor"] or {}), "described": data}
        elif event == "answer-parts-unplaceable":
            run["editor"] = {
                **(run["editor"] or {}),
                "kind": data.get("editorKind"),
                "count": data.get("editorCount"),
                "kinds": data.get("editorKinds"),
                "enabled": data.get("editorEnabled"),
                "allowed": data.get("allowed"),
                "templates": data.get("templates"),
                "direct_fit": data.get("directFit"),
                "planned_fit": data.get("plannedFit"),
            }
        elif event in {"solved", "graph-plan-validated"}:
            run["route"] = {
                "source": data.get("source"),
                "answered_by": data.get("answeredBy"),
                "facet_invoked": data.get("facetInvoked"),
                "router": data.get("facetRouter"),
                "method": data.get("facetMethod"),
                "reading": data.get("facetReading"),
                "insertable": data.get("insertable"),
                "elapsed_ms": data.get("elapsedMs"),
            }
            run["runtime"] = {
                "runtime": data.get("facetRuntime"),
                "model": data.get("facetModel"),
                "requested_backend": data.get("facetRequestedBackend"),
                "backend": data.get("facetBackend") or data.get("backend"),
                "device": data.get("facetDevice") or data.get("device"),
                "fallback": data.get("facetFallback"),
            }
            run["answer_length"] = data.get("answerLength")
            if data.get("stages"):
                run["stages"] = str(data["stages"]).split(">")
            run["outcome"] = "solved"
        elif event == "insertion-pinned":
            run["ownership"] = {"pinned": data, "changed": [], "why": ""}
            run["solved_in"] = data.get("solvedIn") or None
        elif event == "insertion-target-changed":
            run["ownership"] = {
                "pinned": data.get("pinned", (run["ownership"] or {}).get("pinned")),
                "changed": [c for c in str(data.get("changed", "")).split(",") if c],
                "why": data.get("why", ""),
                "now_phase": data.get("nowPhase"),
            }
            run["outcome"] = "abandoned"
        elif event == "cadence-performed":
            run["cadence"] = data
        elif event == "inserted":
            run["outcome"] = "inserted"
            run["insertion"] = {
                "via": data.get("via"),
                "elapsed_ms": data.get("elapsedMs"),
                "answer_length": data.get("answerLength"),
            }
        elif event == "failed":
            run["outcome"] = "failed"
            run["error_key"] = data.get("errorKey", "")
            run["failed_at_stage"] = data.get("stage")
            if data.get("stages"):
                run["stages"] = str(data["stages"]).split(">")
        elif event == "answer-not-insertable":
            run["not_insertable"] = {
                "editor": data.get("editor"),
                "plan": data.get("plan"),
                "source": data.get("source"),
            }

    run["first_failing_stage"] = _first_failing_stage(run)
    run["failure"] = classify(run)
    run["events_seen"] = sorted(seen)
    return run


def _first_failing_stage(run: dict) -> str | None:
    """The stage the run stopped in, named from the trail rather than guessed.

    `failed at solving` was the only thing the ring ever said, and it is true of
    a capture that never happened and of a model that answered nothing alike.
    """
    if run["outcome"] not in {"failed", "abandoned", "incomplete"}:
        return None
    if run.get("failed_at_stage"):
        return run["failed_at_stage"]
    return run["stages"][-1] if run["stages"] else None


def classify(run: dict) -> dict | None:
    """Which of the seven kinds of failure this was, and what said so."""
    if run["outcome"] in {"solved", "inserted"} and not run.get("not_insertable"):
        return None
    if run["outcome"] == "incomplete" and not run["error_key"]:
        if "answer-not-insertable" not in run["events_seen"] and not run.get(
            "not_insertable"
        ):
            return None
    for name, matches, why in FAILURE_RULES:
        try:
            if matches(run):
                return {"class": name, "why": why, "error_key": run["error_key"]}
        except (KeyError, TypeError):
            continue
    return {"class": "unclassified", "why": "no rule matched", "error_key": run["error_key"]}


# --- the machines behind the browser --------------------------------------


def _ollama(path: str) -> dict | None:
    try:
        with urllib.request.urlopen(f"{OLLAMA_ROOT}{path}", timeout=OLLAMA_TIMEOUT) as reply:
            return json.load(reply)
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError):
        return None


def ollama_state(needed: bool) -> dict:
    """The local runner, and only when a run actually reached a model.

    Asked unconditionally this would be noise on every observation of a
    question the exact solvers answered in under a second -- which is most of
    them. `needed` is decided from the runs, not from a flag.
    """
    if not needed:
        return {"record": "ollama", "asked": False, "why": "no run reached a runtime"}
    state = {"record": "ollama", "asked": True}
    try:
        sys.path.insert(0, str(RUNTIME_ROOT / "src"))
        from facet_runtime.discovery import _ollama_status  # noqa: PLC0415

        state["service"] = _ollama_status()
    except Exception as error:  # noqa: BLE001 - Facet's own probe, best effort
        state["service"] = {"error": f"{type(error).__name__}: {error}"}
    running = _ollama("/api/ps")
    if running is None:
        state["runner"] = None
        state["failure_reason"] = (
            "the local Ollama HTTP endpoint did not answer; a run that reported a "
            "model ran somewhere else, or the runner has since stopped"
        )
        return state
    state["runner"] = [
        {
            "model": model.get("name"),
            "size": model.get("size"),
            "size_vram": model.get("size_vram"),
            "resident": bool(model.get("size_vram")),
            "expires_at": model.get("expires_at"),
        }
        for model in running.get("models", [])
    ]
    if not state["runner"]:
        state["failure_reason"] = (
            "no model is loaded now; a solve that took a model's time has since "
            "been unloaded, which is ordinary between questions"
        )
    return state


def facet_summary(runs: list[dict], extension_store: dict) -> dict:
    """Route, backend, model and device, from the runs and the last observed."""
    routed = [run for run in runs if run.get("runtime") and run["runtime"].get("model")]
    return {
        "record": "facet",
        "target": os.environ.get("FACET_SSH_TARGET", "steve@192.168.0.247"),
        "runs_that_reached_a_runtime": len(routed),
        "observed": [
            {
                "run": run["run"],
                **{key: value for key, value in run["runtime"].items() if value not in (None, "")},
                "answered_by": (run.get("route") or {}).get("answered_by"),
                "source": (run.get("route") or {}).get("source"),
            }
            for run in routed
        ],
        "last_seen_by_settings_page": extension_store.get("facetLastSeen"),
    }


# --- assembling one observation -------------------------------------------


def observe(
    *,
    match: str | None = None,
    last: int = 400,
    only_run: str | None = None,
    want_screenshot: bool = False,
    bundle: Path | None = None,
) -> list[dict]:
    reference = clock()
    records: list[dict] = [reference]
    reader = _load("read_extension_log")
    inspector = _load("inspect_live_firefox")

    # --- the trees ---------------------------------------------------------
    records.append(
        {
            "record": "repositories",
            "facet-hawkes": repository(PROJECT_ROOT),
            "facet-runtime": repository(RUNTIME_ROOT),
        }
    )

    # --- the browser -------------------------------------------------------
    windows: list[dict] = []
    window_note = None
    try:
        windows = inspector._kwin_windows()
    except Exception as error:  # noqa: BLE001 - no KWin is a degraded observation
        window_note = f"{type(error).__name__}: {error}"
    firefox = None
    if windows:
        try:
            firefox = inspector._one_firefox_window(windows, match)
        except inspector.InspectionError as error:
            window_note = str(error)
    records.append(
        {
            "record": "windows",
            "note": window_note,
            "firefox_windows": [
                {
                    "caption": window.get("caption"),
                    "pid": window.get("pid"),
                    "active": window.get("active"),
                    "minimized": window.get("minimized"),
                    "chosen": firefox is not None and window is firefox,
                }
                for window in windows
                if window.get("resourceClass") == inspector.FIREFOX_CLASS
                and window.get("normalWindow")
            ],
            "previously_active": next(
                (w.get("caption") for w in windows if w.get("active")), None
            ),
        }
    )

    # --- the add-on --------------------------------------------------------
    install = inspector._extension_status()
    entries: list[dict] = []
    store: dict = {}
    log_note = None
    try:
        profile = reader.find_profile(install.get("profile"))
        store_path = reader.find_store(profile)
        entries = reader.read_entries(store_path)
        store = _stored_values(reader, store_path)
    except Exception as error:  # noqa: BLE001 - an unreadable ring is a finding
        log_note = f"{type(error).__name__}: {error}"

    loads = [e for e in entries if e.get("event") == "event-page-loaded"]
    markers = [e for e in entries if e.get("event") == "build-marker"]
    last_load = loads[-1] if loads else None
    running_marker = _data(markers[-1]) if markers else {}
    tree_marker = working_tree_marker()
    records.append(
        {
            "record": "extension",
            "install": install,
            "log_note": log_note,
            "generations": sorted({e["gen"] for e in entries if e.get("gen")}),
            "event_page_loads": len(loads),
            "last_event_page_load": _stamp(last_load.get("t"), reference) if last_load else None,
            "last_load_settings": _data(last_load) if last_load else None,
        }
    )
    records.append(code_verdict(running_marker, tree_marker, last_load, install))

    # --- the runs ----------------------------------------------------------
    kept = entries[-last:] if last else entries
    runs = [summarize_run(group, reference) for group in group_runs(kept)]
    if only_run:
        runs = [run for run in runs if run["run"] == only_run]
    records.extend(runs)

    # --- what answered them ------------------------------------------------
    records.append(
        {
            "record": "native_host",
            "processes": inspector._matching_processes(
                ("ethnos.hawkes_host", "ethnos-hawkes-host")
            ),
            "correlation": "request ids are <run>.<n>; grep a run id to find its host call",
        }
    )
    records.append(facet_summary(runs, store))
    # Asked only when a run actually named a runtime. Most questions are
    # answered exactly, in under a second, without a model being involved at
    # all; probing on those would add a section that says nothing.
    reached_a_runtime = any(
        (run.get("runtime") or {}).get("model") or (run.get("runtime") or {}).get("backend")
        for run in runs
    )
    records.append(ollama_state(reached_a_runtime))

    cadence_runs = [run for run in runs if run.get("cadence")]
    records.append(
        {
            "record": "cadence",
            "participated": bool(cadence_runs),
            "runs": [{"run": run["run"], **run["cadence"]} for run in cadence_runs],
        }
    )

    # --- the tail, and a picture if one is wanted --------------------------
    records.append(
        {
            "record": "log_tail",
            "entries": [
                {
                    "at": _stamp(entry.get("t"), reference),
                    "level": entry.get("level"),
                    "scope": entry.get("scope"),
                    "gen": entry.get("gen"),
                    "run": entry.get("run"),
                    "event": entry.get("event"),
                    "data": entry.get("data"),
                }
                for entry in kept[-80:]
            ],
        }
    )
    records.append(_screenshot(inspector, want_screenshot, bundle, match, runs))
    return records


def _stored_values(reader, store_path: Path) -> dict:
    """The add-on's own non-log storage, for the settings page's Facet note."""
    found: dict = {}
    try:
        import shutil
        import sqlite3

        with tempfile.TemporaryDirectory(prefix="hawkes-observe-") as work:
            copy = Path(work) / "store.sqlite"
            shutil.copy(store_path, copy)
            rows = sqlite3.connect(copy).execute("select data from object_data").fetchall()
        for (blob,) in rows:
            if not blob:
                continue
            value = reader.Clone(reader.snappy_decompress(bytes(blob))).read()
            if isinstance(value, dict) and "facetLastSeen" in value:
                found["facetLastSeen"] = value["facetLastSeen"]
    except Exception:  # noqa: BLE001 - a cosmetic field; absence is not a fault
        return found
    return found


def code_verdict(running: dict, tree: dict, last_load: dict | None, install: dict) -> dict:
    """Whether the code Firefox is running is the code in this tree.

    Two independent checks, because neither alone is enough. The marker says
    what the running build folded to; the file times say whether anything has
    been edited since that build was loaded. A build predating the marker
    answers only the second, which is still the answer that would have saved
    the two lost afternoons.
    """
    changed = touched_after(last_load.get("t") if last_load else None)
    verdict, why = "unknown", ""
    if not running:
        verdict = "unmarked-build"
        why = (
            "the running add-on logged no build marker: it predates this tooling. "
            "Reload it in about:debugging to get one."
        )
    elif not tree.get("computed"):
        verdict = "uncomparable"
        why = tree.get("why", "the tree's marker could not be computed")
    elif running.get("marker") == tree.get("marker"):
        verdict = "running-this-tree"
        why = "the running build folds to the same marker as the working tree"
    else:
        verdict = "running-other-code"
        why = (
            "the running build folds to a different marker than the working tree: "
            "Firefox is not running what is on disk. Reload the add-on."
        )
    if changed and verdict == "running-this-tree":
        verdict = "running-this-tree-but-edited-since"
        why = (
            "the marker matched, but files have been written since the event page "
            "loaded; if the add-on has not been reloaded those edits are not live"
        )
    return {
        "record": "code",
        "verdict": verdict,
        "why": why,
        "running": running,
        "working_tree": tree,
        "changed_since_event_page_loaded": changed,
        "installed_as": "temporary" if install.get("temporary") else "packaged",
        "manifest_version": install.get("version"),
        "covers": (
            "the event page's own code and every binding it imports. The panel, "
            "the settings page and the injected content scripts load elsewhere "
            "and are covered by the repository state above, not by this marker."
        ),
    }


def _screenshot(inspector, wanted: bool, bundle: Path | None, match: str | None, runs) -> dict:
    """Capture only when asked, only into a bundle, and say it must be deleted."""
    failing = [run for run in runs if run.get("failure")]
    if not wanted:
        return {
            "record": "screenshot",
            "taken": False,
            "why": "not requested"
            + ("; a failing run is present, --screenshot would capture it" if failing else ""),
        }
    if bundle is None:
        return {
            "record": "screenshot",
            "taken": False,
            "why": "--screenshot needs --bundle: a coursework capture belongs in a "
            "directory with a deletion command, not loose in /tmp",
        }
    try:
        path = inspector.shot(bundle / "firefox-window.png", match)
    except Exception as error:  # noqa: BLE001 - never fail an observation over a picture
        return {"record": "screenshot", "taken": False, "why": f"{type(error).__name__}: {error}"}
    return {
        "record": "screenshot",
        "taken": True,
        "path": str(path),
        "warning": "COURSEWORK. Inspect, then delete the bundle.",
    }


# --- the human half --------------------------------------------------------


def _find(records: list[dict], name: str) -> dict:
    return next((record for record in records if record.get("record") == name), {})


def summarize(records: list[dict]) -> str:
    """The same evidence, short enough to read before deciding what to open."""
    out: list[str] = []
    reference = _find(records, "clock")
    repos = _find(records, "repositories")
    code = _find(records, "code")
    extension = _find(records, "extension")
    windows = _find(records, "windows")
    runs = [record for record in records if record.get("record") == "run"]

    out.append("LIVE HAWKES OBSERVATORY")
    out.append(f"  observed   {reference.get('local')}  ({reference.get('utc')} UTC)")
    for name in ("facet-hawkes", "facet-runtime"):
        repo = repos.get(name, {})
        if not repo.get("present"):
            out.append(f"  {name:<12} not present at {repo.get('path')}")
            continue
        dirt = f"dirty:{repo['dirty_count']}" if repo["dirty"] else "clean"
        out.append(
            f"  {name:<12} {repo.get('short')} {dirt:<10} {repo.get('branch')}"
            f"  {str(repo.get('subject'))[:52]}"
        )

    out.append("")
    out.append("CODE FIREFOX IS RUNNING")
    out.append(f"  verdict    {code.get('verdict')}")
    out.append(f"             {code.get('why')}")
    running, tree = code.get("running") or {}, code.get("working_tree") or {}
    out.append(
        f"  marker     running={running.get('marker', '-')}"
        f"  tree={tree.get('marker', '-') if tree.get('computed') else '-'}"
        f"  symbols={running.get('symbols', '-')}"
    )
    out.append(
        f"  install    {code.get('installed_as')} v{code.get('manifest_version')}"
        f"  generations seen: {len(extension.get('generations') or [])}"
        f"  event-page loads: {extension.get('event_page_loads')}"
    )
    if code.get("changed_since_event_page_loaded"):
        listed = code["changed_since_event_page_loaded"]
        out.append(f"  edited     {len(listed)} file(s) written since the page loaded:")
        for path in listed[:6]:
            out.append(f"               {path}")
    last_load = extension.get("last_event_page_load")
    if last_load:
        out.append(f"  loaded at  {last_load['local']}  ({last_load['ago_seconds']}s ago)")
    if extension.get("log_note"):
        out.append(f"  log        {extension['log_note']}")

    out.append("")
    out.append("BROWSER")
    if windows.get("note"):
        out.append(f"  note       {windows['note']}")
    for window in windows.get("firefox_windows", []):
        mark = "->" if window.get("chosen") else "  "
        flags = "active" if window.get("active") else ""
        out.append(f"  {mark} pid {window.get('pid')} {flags:<7} {str(window.get('caption'))[:70]}")

    out.append("")
    out.append(f"RUNS ({len(runs)}) — newest last")
    for run in runs:
        out.extend(_run_lines(run))

    for name, title in (
        ("native_host", "NATIVE HOST"),
        ("facet", "FACET"),
        ("ollama", "OLLAMA"),
        ("cadence", "CADENCE"),
        ("screenshot", "SCREENSHOT"),
    ):
        record = _find(records, name)
        out.append("")
        out.append(title)
        out.extend(f"  {line}" for line in _record_lines(name, record))
    return "\n".join(out)


def _run_lines(run: dict) -> list[str]:
    guessed = "" if run["correlated"] else "  (grouped by adjacency, not by run id)"
    head = (
        f"  {run['run']}  {run['outcome']}"
        f"  {(run['started'] or {}).get('local', '')[11:23]}"
        f"  +{run['elapsed_ms']}ms{guessed}"
    )
    lines = [head]
    if len(run["generations"]) > 1:
        lines.append(f"     lifecycle  spans {len(run['generations'])} event pages")
    if run.get("target"):
        lines.append(f"     target     {_compact(run['target'])}")
    if run.get("signature"):
        lines.append(f"     question   sig={run['signature']}")
    if run.get("question"):
        lines.append(f"     evidence   {_compact(run['question'])}")
    if run.get("editor"):
        lines.append(f"     editor     {_compact(run['editor'])}")
    if run["stages"]:
        lines.append(f"     stages     {' > '.join(run['stages'])}")
    if run.get("route"):
        lines.append(f"     route      {_compact(run['route'])}")
    if run.get("runtime") and any(run["runtime"].values()):
        lines.append(f"     ran on     {_compact(run['runtime'])}")
    if run.get("ownership"):
        own = run["ownership"]
        changed = ",".join(own.get("changed") or []) or "nothing"
        joined = f" solved-in={run['solved_in']}" if run.get("solved_in") else ""
        lines.append(
            f"     ownership  changed={changed} at={own.get('why') or 'pinned'}{joined}"
        )
    if run.get("not_insertable"):
        lines.append(f"     refused    {_compact(run['not_insertable'])}")
    if run.get("cadence"):
        lines.append(f"     cadence    notes={run['cadence'].get('notes')}")
    if run.get("first_failing_stage"):
        lines.append(f"     stopped in {run['first_failing_stage']}")
    if run.get("failure"):
        failure = run["failure"]
        lines.append(
            f"     FAILURE    {failure['class']}"
            + (f" ({failure['error_key']})" if failure.get("error_key") else "")
        )
        lines.append(f"                {failure['why']}")
    return lines


def _record_lines(name: str, record: dict) -> list[str]:
    if name == "native_host":
        processes = record.get("processes") or []
        if not processes:
            return ["no host process running (it exits between solves; this is normal)"]
        return [f"pid {p['pid']}  {p['command'][:80]}" for p in processes]
    if name == "facet":
        lines = [f"target {record.get('target')}"]
        for seen in record.get("observed", []):
            lines.append(_compact(seen))
        if not record.get("observed"):
            lines.append("no run in this window reached a runtime")
        if record.get("last_seen_by_settings_page"):
            lines.append(f"last observed: {_compact(record['last_seen_by_settings_page'])}")
        return lines
    if name == "ollama":
        if not record.get("asked"):
            return [str(record.get("why"))]
        lines = [_compact(record.get("service") or {})]
        for model in record.get("runner") or []:
            lines.append(_compact(model))
        if record.get("failure_reason"):
            lines.append(record["failure_reason"])
        return lines
    if name == "cadence":
        if not record.get("participated"):
            return ["did not participate in any run in this window"]
        return [_compact(run) for run in record.get("runs", [])]
    if name == "screenshot":
        if not record.get("taken"):
            return [str(record.get("why"))]
        return [str(record.get("path")), str(record.get("warning"))]
    return [_compact(record)]


def _compact(value: dict) -> str:
    parts = []
    for key, inner in value.items():
        if inner in (None, "", [], {}, False) or key == "record":
            continue
        parts.append(f"{key}={json.dumps(inner, default=str) if isinstance(inner, (dict, list)) else inner}")
    return " ".join(parts) or "-"


# --- entry point -----------------------------------------------------------


def _writable_bundle(explicit: str | None) -> Path:
    path = (
        Path(explicit).expanduser()
        if explicit
        else Path(tempfile.mkdtemp(prefix="hawkes-observatory-"))
    )
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--match", help="Substring of the Firefox window title to mean.")
    parser.add_argument("--last", type=int, default=400, help="Log entries to consider.")
    parser.add_argument("--run", help="Only this run id.")
    parser.add_argument("--json", action="store_true", help="JSONL to stdout, no summary.")
    parser.add_argument(
        "--bundle",
        nargs="?",
        const="",
        help="Write observation.jsonl and summary.txt to a directory.",
    )
    parser.add_argument(
        "--screenshot",
        action="store_true",
        help="Capture the chosen Firefox window into the bundle. Coursework: delete it.",
    )
    args = parser.parse_args()

    bundle = _writable_bundle(args.bundle or None) if args.bundle is not None else None
    try:
        records = observe(
            match=args.match,
            last=args.last,
            only_run=args.run,
            want_screenshot=args.screenshot,
            bundle=bundle,
        )
    except ObservationError as error:
        print(f"observation refused: {error}", file=sys.stderr)
        return 1

    text = summarize(records)
    if bundle is not None:
        (bundle / "observation.jsonl").write_text(
            "".join(json.dumps(record, default=str) + "\n" for record in records),
            encoding="utf-8",
        )
        (bundle / "summary.txt").write_text(text + "\n", encoding="utf-8")
        for child in bundle.iterdir():
            child.chmod(0o600)
    if args.json:
        for record in records:
            print(json.dumps(record, default=str))
    else:
        print(text)
    if bundle is not None:
        print(f"\nbundle   {bundle}")
        print(f"delete   rm -rf {bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
