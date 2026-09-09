#!/usr/bin/env python3
"""Triage the failures a live Hawkes session recorded while nobody was watching.

The observatory answers "what is happening now", and answering it needs the
session to still be there. That is the whole problem it could not solve: a
refusal from an hour ago has had its ring entries pushed out by ordinary use,
so diagnosing one meant an agent staying attached to the browser and catching
it live. A vigil is not a diagnostic.

So the add-on now keeps its own bounded ledger of runs that ended in a
diagnostic terminal state -- failed, refused, or answered in a shape the editor
will not take -- and this reads it back, offline, grouped by what kind of
failure it was. Firefox does not have to be running. Nothing here is live.

    python3 scripts/triage_hawkes_failures.py
    python3 scripts/triage_hawkes_failures.py --group f1:ce992b2738bf1098
    python3 scripts/triage_hawkes_failures.py --run r2f8xk91c4
    python3 scripts/triage_hawkes_failures.py --export f1:ce992b2738bf1098

What it does *not* do is again the point. It runs no command: no `git`, no
window manager, no screenshot, nothing. It reads two things -- the add-on's
storage, through a throwaway copy of the profile database, and its own source
tree for the two lists below -- and prints. It never connects to the add-on,
never touches the page, and cannot wake a suspended event page, so it is safe
to run in the middle of the owner's question.

It records no coursework because there is none to record: the ledger holds
shapes, counts, the page's own vocabulary for its editor, and identifiers this
profile minted. An exported bundle is filtered a second time, through the
add-on's own allowlist, so a hand-edited profile still cannot put a student's
answer into a file meant to be shared.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS.parent
EXTENSION_DIR = PROJECT_ROOT / "extension"
RECORD_MODULE = EXTENSION_DIR / "common" / "failure-record.js"
LOG_MODULE = EXTENSION_DIR / "common" / "log.js"


class TriageError(RuntimeError):
    """The ledger could not be read, or an export was refused."""


def _load(name: str):
    """Import a sibling script as a module, rather than re-implementing it."""
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    if spec is None or spec.loader is None:  # pragma: no cover - packaging fault
        raise TriageError(f"cannot load {name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- the add-on's own declarations, read rather than restated --------------


def _js_string_array(source: str, name: str) -> list[str]:
    """The contents of a `const NAME = Object.freeze([...])` in a module."""
    match = re.search(
        rf"{re.escape(name)}\s*=\s*Object\.freeze\(\s*\[(.*?)\]", source, re.S
    )
    if match is None:
        match = re.search(
            rf"{re.escape(name)}\s*=\s*new Set\(\s*\[(.*?)\]", source, re.S
        )
    if match is None:
        return []
    return re.findall(r'"([^"]+)"', match.group(1))


def _js_number(source: str, name: str) -> int | None:
    """A numeric `const` from a module, including a small product like `14 * 24`."""
    match = re.search(rf"{re.escape(name)}\s*=\s*([0-9*\s]+);", source)
    if match is None:
        return None
    parts = [int(part) for part in re.findall(r"\d+", match.group(1))]
    total = 1
    for part in parts:
        total *= part
    return total


def contract() -> dict:
    """What a record may contain and how much of it is kept.

    Parsed out of `common/failure-record.js` and `common/log.js` rather than
    copied here. A second copy of an allowlist is a second copy that can fall
    behind, and the failure it produces -- a field the browser stores and this
    tool silently drops, or worse, one it lets through -- is exactly the kind
    that nobody notices until it matters.
    """
    if not RECORD_MODULE.is_file() or not LOG_MODULE.is_file():
        raise TriageError(
            f"cannot read the add-on's own field allowlist from {RECORD_MODULE}; "
            "refusing to sanitize by guesswork"
        )
    record_source = RECORD_MODULE.read_text(encoding="utf-8")
    log_source = LOG_MODULE.read_text(encoding="utf-8")
    safe = _js_string_array(record_source, "SAFE_RECORD_KEYS")
    sensitive = _js_string_array(log_source, "SENSITIVE")
    if not safe or not sensitive:
        raise TriageError(
            "the add-on's allowlists could not be read; refusing to export"
        )
    return {
        "safe_record_keys": safe,
        "sensitive_keys": sensitive,
        "max_records": _js_number(record_source, "MAX_RECORDS"),
        "max_groups": _js_number(record_source, "MAX_GROUPS"),
        "max_age_ms": _js_number(record_source, "MAX_AGE_MS"),
        "max_bytes": _js_number(record_source, "MAX_BYTES"),
        "max_string": _js_number(log_source, "MAX_STRING"),
        "fingerprint_version": (
            re.search(r'FINGERPRINT_VERSION\s*=\s*"([^"]+)"', record_source)
            or [None, "f1"]
        )[1],
        "storage_key": (
            re.search(r'FAILURE_STORAGE_KEY\s*=\s*"([^"]+)"', record_source)
            or [None, "failures"]
        )[1],
        "ledger_version": _js_number(record_source, "LEDGER_VERSION"),
    }


# --- reading the ledger ----------------------------------------------------


def read_ledger(profile: str | None = None, path: str | None = None) -> dict:
    """The stored ledger, from a profile or from a file an export produced."""
    terms = contract()
    if path:
        raw = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        ledger = raw.get("ledger", raw)
        return {
            "ledger": _as_ledger(ledger),
            "source": f"file: {path}",
            "label": "file",
            "entries": raw.get("ring", []),
        }
    reader = _load("read_extension_log")
    found = reader.find_profile(profile)
    store = reader.find_store(found)
    stored = reader.read_storage(store)
    return {
        "ledger": _as_ledger(stored.get(terms["storage_key"])),
        "source": f"profile: {found.name}",
        "label": "profile",
        "entries": reader.read_entries(store),
    }


def _as_ledger(value) -> dict:
    blank = {"version": 0, "records": [], "groups": [], "dropped": {}}
    if not isinstance(value, dict):
        return blank
    return {
        "version": value.get("version", 0),
        "records": [r for r in value.get("records") or [] if isinstance(r, dict)],
        "groups": [g for g in value.get("groups") or [] if isinstance(g, dict)],
        "dropped": value.get("dropped")
        if isinstance(value.get("dropped"), dict)
        else {},
    }


# --- sanitizing ------------------------------------------------------------


def sanitize_record(record: dict, terms: dict) -> dict:
    """One record, filtered through the add-on's own allowlist.

    The browser already builds records by name, so nothing that reaches here
    should need filtering. This runs anyway, because `storage.local` is a file
    on the owner's disk that anything with a debugger can write, and a bundle
    is the one artefact of this whole system that is meant to be handed to
    somebody else.
    """
    return {
        key: _scrub(record[key], key, terms)
        for key in terms["safe_record_keys"]
        if key in record
    }


def _scrub(value, key: str, terms: dict):
    """Drop anything named like coursework, and bound everything else."""
    if key in terms["sensitive_keys"]:
        if isinstance(value, str):
            return {"length": len(value)}
        return None if value is None else {"present": True}
    if isinstance(value, str):
        limit = terms["max_string"] or 160
        return value if len(value) <= limit else f"{value[:limit]}…"
    if isinstance(value, bool) or isinstance(value, (int, float)) or value is None:
        return value
    if isinstance(value, list):
        return [_scrub(item, "", terms) for item in value[:32]]
    if isinstance(value, dict):
        return {
            name: _scrub(inner, name, terms) for name, inner in list(value.items())[:32]
        }
    return str(value)[: terms["max_string"] or 160]


#: What a ring entry may carry into a bundle. `data` is scrubbed by key below.
RING_ENTRY_KEYS = ("t", "seq", "level", "scope", "gen", "run", "event", "data")


def sanitize_entry(entry: dict, terms: dict) -> dict:
    return {
        key: _scrub(entry[key], key, terms) for key in RING_ENTRY_KEYS if key in entry
    }


# --- classification, borrowed rather than restated -------------------------


def classify(
    observatory, record_or_group: dict, generations: list[str] | None = None
) -> dict:
    """The failure class of one group, named by the observatory's own rules.

    The eight classes are declared once, in `observe_live_hawkes.py`, with the
    evidence that puts a run in each, and the adapter from a ledger record to
    that shape lives beside them. Restating either here would let a bundle and
    an observation disagree about what kind of failure the same run was --
    precisely the confusion both tools exist to end.
    """
    return observatory.classify_ledger(record_or_group, generations)


# --- grouping --------------------------------------------------------------


def triage(read: dict) -> dict:
    """Every group, classified, counted and joined back to what is still around."""
    observatory = _load("observe_live_hawkes")
    terms = contract()
    ledger = read["ledger"]
    now_ms = round(time.time() * 1000)

    by_run: dict[str, list[dict]] = {}
    for entry in read.get("entries") or []:
        run = entry.get("run")
        if run:
            by_run.setdefault(run, []).append(entry)

    records = sorted(ledger["records"], key=lambda record: record.get("at") or 0)
    retained: dict[str, list[dict]] = {}
    for record in records:
        retained.setdefault(record.get("fingerprint") or "", []).append(record)

    groups = []
    for group in ledger["groups"]:
        mark = group.get("fingerprint") or ""
        mine = retained.get(mark, [])
        runs = list(dict.fromkeys([group.get("firstRun"), *(group.get("runs") or [])]))
        runs = [run for run in runs if run]
        # A run whose ring entries span two generations outlived its own event
        # page. The record cannot know that -- the page that would have noticed
        # is the one that went away -- so it is read back off the ring, for as
        # long as the ring still has it.
        seen_generations = list(group.get("generations") or [])
        ring_generations: dict[str, list[str]] = {}
        for run in runs:
            spans = sorted({e.get("gen") for e in by_run.get(run, []) if e.get("gen")})
            if spans:
                ring_generations[run] = spans
                seen_generations.extend(spans)
        spanning = sorted(
            run for run, spans in ring_generations.items() if len(spans) > 1
        )
        # Classified from what the group itself recorded, never from the ring.
        # One run of six having outlived its event page does not make the other
        # five lifecycle failures, and a record is always written by exactly one
        # lifetime -- a run that genuinely turns over loses its run id with the
        # page, so it leaves no record to reclassify. The spanning runs are
        # reported below as what they are: an observation about those runs.
        verdict = classify(observatory, group)
        groups.append(
            {
                "fingerprint": mark,
                "classification": verdict["class"],
                "why": verdict["why"],
                "count": group.get("count") or 0,
                "first_seen": group.get("firstSeen"),
                "last_seen": group.get("lastSeen"),
                "error_key": group.get("errorKey") or "",
                "outcome": group.get("outcome") or "",
                "stopped_in": group.get("stoppedIn") or "",
                "editor_kind": group.get("editorKind") or "",
                "runs": runs,
                "first_run": group.get("firstRun") or "",
                "markers": list(group.get("markers") or []),
                "generations": sorted(set(seen_generations)),
                "runs_spanning_generations": spanning,
                "records_retained": len(mine),
                "records_evicted": max(0, (group.get("count") or 0) - len(mine)),
                "records": mine,
                "ring_entries": {run: len(by_run.get(run, [])) for run in runs},
                "age_seconds": _age(group.get("lastSeen"), now_ms),
            }
        )

    groups.sort(key=lambda g: (-g["count"], -(g["last_seen"] or 0)))
    # A fingerprint names the fields it was folded from. Change those fields and
    # the same fault gets a new name, so a ledger carrying two eras of them
    # would silently report one problem as two. The prefix is what says which.
    era = f"{terms['fingerprint_version']}:"
    foreign = sorted(
        {
            group["fingerprint"]
            for group in groups
            if not group["fingerprint"].startswith(era)
        }
    )
    classes: dict[str, dict] = {}
    for group in groups:
        bucket = classes.setdefault(
            group["classification"], {"groups": 0, "occurrences": 0}
        )
        bucket["groups"] += 1
        bucket["occurrences"] += group["count"]

    return {
        "read_at": now_ms,
        "source": read["source"],
        "source_label": read.get("label", "profile"),
        "ledger_version": ledger["version"],
        "expected_version": terms["ledger_version"],
        "records": len(records),
        "groups": groups,
        "occurrences": sum(group["count"] for group in groups),
        "classes": classes,
        "dropped": ledger["dropped"],
        "fingerprint_version": terms["fingerprint_version"],
        "foreign_fingerprints": foreign,
        "bytes": len(json.dumps(ledger, default=str)),
        "bounds": {
            "records": terms["max_records"],
            "groups": terms["max_groups"],
            "age_days": round((terms["max_age_ms"] or 0) / 86_400_000, 1),
            "bytes": terms["max_bytes"],
        },
        "window": {
            "first": min((g["first_seen"] or 0 for g in groups), default=0),
            "last": max((g["last_seen"] or 0 for g in groups), default=0),
        },
    }


def _age(when_ms, now_ms: int):
    if not isinstance(when_ms, (int, float)) or not when_ms:
        return None
    return round((now_ms - when_ms) / 1000, 1)


# --- the human half --------------------------------------------------------


def _when(when_ms) -> str:
    if not isinstance(when_ms, (int, float)) or not when_ms:
        return "-"
    return (
        datetime.fromtimestamp(when_ms / 1000)
        .astimezone()
        .isoformat(timespec="seconds")
    )


def _ago(seconds) -> str:
    if seconds is None:
        return "-"
    if seconds < 90:
        return f"{round(seconds)}s ago"
    if seconds < 5400:
        return f"{round(seconds / 60)}m ago"
    if seconds < 172800:
        return f"{round(seconds / 3600)}h ago"
    return f"{round(seconds / 86400)}d ago"


def _pairs(value: dict, keys=()) -> str:
    names = keys or list(value)
    parts = []
    for key in names:
        inner = value.get(key)
        if inner in (None, "", [], {}, False):
            continue
        if isinstance(inner, (dict, list)):
            inner = json.dumps(inner, separators=(",", ":"), default=str)
        parts.append(f"{key}={inner}")
    return " ".join(parts) or "-"


def report(view: dict, *, detail: str | None = None) -> str:
    out: list[str] = []
    out.append("HAWKES FAILURE TRIAGE")
    out.append(f"  read       {_when(view['read_at'])}   {view['source']}")
    if view["records"] == 0 and not view["groups"]:
        out.append(
            "  ledger     empty -- nothing has failed, or the ledger was cleared"
        )
        if view["ledger_version"] not in (0, view["expected_version"]):
            out.append(
                f"  version    stored {view['ledger_version']}, this build writes "
                f"{view['expected_version']}: the ledger was written by another build"
            )
        out.append("")
        out.append("Nothing to triage. Use Hawkes normally; failures accumulate here.")
        return "\n".join(out)

    bounds = view["bounds"]
    out.append(
        f"  ledger     {view['records']} records · {len(view['groups'])} groups · "
        f"{view['occurrences']} occurrences · {view['bytes'] / 1024:.1f} KB"
    )
    out.append(
        f"  retention  {bounds['records']} records, {bounds['groups']} groups, "
        f"{bounds['age_days']} days, {(bounds['bytes'] or 0) / 1024:.0f} KB"
        "  (oldest evicted first)"
    )
    dropped = view["dropped"] or {}
    out.append(
        f"  evicted    {dropped.get('age', 0)} by age · {dropped.get('count', 0)} by count"
        f" · {dropped.get('bytes', 0)} by size"
    )
    out.append(
        f"  window     first {_when(view['window']['first'])}"
        f"   last {_when(view['window']['last'])}"
    )
    if view["ledger_version"] not in (0, view["expected_version"]):
        out.append(
            f"  version    stored {view['ledger_version']}, this tree writes "
            f"{view['expected_version']}: another build wrote this ledger"
        )
    if view["foreign_fingerprints"]:
        out.append(
            f"  era        {len(view['foreign_fingerprints'])} group(s) were fingerprinted "
            f"by rules other than {view['fingerprint_version']}: the same fault may "
            "appear under two names"
        )

    shown = (
        view["groups"]
        if detail is None
        else [
            group
            for group in view["groups"]
            if group["fingerprint"] == detail or detail in group["runs"]
        ]
    )
    if detail is not None and not shown:
        out.append("")
        out.append(f"No group or run matches {detail!r}.")
        return "\n".join(out)

    for name in sorted(
        {group["classification"] for group in shown},
        key=lambda name: -view["classes"].get(name, {}).get("occurrences", 0),
    ):
        summary = view["classes"].get(name, {})
        out.append("")
        out.append(
            f"{name.upper()}  ({summary.get('groups', 0)} group(s), "
            f"{summary.get('occurrences', 0)} occurrence(s))"
        )
        for group in [g for g in shown if g["classification"] == name]:
            out.extend(_group_lines(group, full=detail is not None))

    out.append("")
    out.append("NEXT")
    first = shown[0] if shown else None
    if first:
        out.append(
            f"  detail     python3 scripts/triage_hawkes_failures.py --group {first['fingerprint']}"
        )
        out.append(
            f"  bundle     python3 scripts/triage_hawkes_failures.py --export {first['fingerprint']}"
        )
        if first["runs"]:
            run = first["runs"][-1]
            out.append(
                f"  ring       python3 scripts/read_extension_log.py --grep {run}"
            )
            out.append(
                f"  live       python3 scripts/observe_live_hawkes.py --run {run}"
            )
    return "\n".join(out)


def _group_lines(group: dict, *, full: bool) -> list[str]:
    lines = [
        f"  {group['fingerprint']}  x{group['count']}  last {_ago(group['age_seconds'])}",
        f"    {group['why']}",
    ]
    facts = [group["error_key"] or group["outcome"]]
    if group["stopped_in"]:
        facts.append(f"stopped in {group['stopped_in']}")
    if group["editor_kind"] and group["editor_kind"] != "none":
        facts.append(f"editor {group['editor_kind']}")
    lines.append(f"    {' · '.join(part for part in facts if part)}")

    latest = group["records"][-1] if group["records"] else None
    if latest:
        lines.extend(f"    {line}" for line in _record_lines(latest, full=full))
    lines.append(
        f"    runs       {' '.join(group['runs']) or '-'}"
        + (f"   (first {group['first_run']})" if group["first_run"] else "")
    )
    if group["markers"]:
        lines.append(f"    builds     {', '.join(group['markers'])}")
    if len(group["generations"]) > 1:
        lines.append(
            f"    lifetimes  {len(group['generations'])} event pages: "
            f"{', '.join(group['generations'][:6])}"
        )
    if group["runs_spanning_generations"]:
        lines.append(
            "    spanning   "
            + " ".join(group["runs_spanning_generations"])
            + "  (outlived its own event page)"
        )
    lines.append(
        f"    records    {group['records_retained']} retained,"
        f" {group['records_evicted']} evicted"
        + (
            "   ring: "
            + " ".join(f"{run}={n}" for run, n in group["ring_entries"].items() if n)
            if any(group["ring_entries"].values())
            else ""
        )
    )
    if full:
        for record in group["records"]:
            lines.append(f"    -- {record.get('run')} {_when(record.get('at'))}")
            lines.extend(f"       {line}" for line in _record_lines(record, full=True))
    return lines


def _record_lines(record: dict, *, full: bool) -> list[str]:
    lines = []
    if record.get("stages"):
        lines.append(f"stages     {' > '.join(record['stages'])}")
    editor = record.get("editor") or {}
    if editor:
        lines.append(
            "editor     "
            + _pairs(
                editor, ("kind", "ok", "count", "enabled", "maxLength", "templates")
            )
        )
        if editor.get("allowed"):
            lines.append(f"allowed    {editor['allowed']!r}")
        if editor.get("slots"):
            lines.append(f"slots      {_pairs(editor['slots'])}")
        for index, control in enumerate(editor.get("controls") or []):
            lines.append(
                f"field {index}    "
                + _pairs(
                    control, ("kind", "enabled", "maxLength", "templates", "allowed")
                )
            )
    traits = record.get("traits") or {}
    if traits.get("transport"):
        # Which writer this run was routed to, or `none:<code>` where the page
        # published no writer for its answer control. Read hours later, with no
        # log ring left, this is often the whole diagnosis of a refusal.
        lines.append(f"transport  {traits['transport']}")
    if traits.get("notInsertable"):
        lines.append(f"refused    {_pairs(traits['notInsertable'])}")
    answer = record.get("answerShape") or {}
    if answer.get("parts") or answer.get("directFit") or answer.get("plannedFit"):
        lines.append(
            f"answer     {_pairs(answer, ('parts', 'directFit', 'plannedFit'))}"
        )
    if record.get("refusal"):
        lines.append(f"refusal    {record['refusal']}")
    evidence = record.get("evidence") or {}
    if evidence:
        lines.append(
            "evidence   "
            + _pairs(evidence, ("read", "expressions", "graph", "table", "promptChars"))
        )
    route = record.get("route") or {}
    if route and any(route.values()):
        lines.append(
            "route      "
            + _pairs(route, ("source", "answeredBy", "router", "method", "reading"))
        )
    runtime = record.get("runtime") or {}
    if runtime and any(runtime.values()):
        lines.append(
            "ran on     "
            + _pairs(runtime, ("runtime", "model", "backend", "device", "fallback"))
        )
    host = record.get("host") or {}
    if host.get("ids"):
        lines.append(f"host       {' '.join(host['ids'])}")
    solve = record.get("solve") or {}
    if solve.get("run"):
        lines.append(
            f"solved in  {solve['run']}  "
            + _pairs(solve.get("runtime") or {}, ("runtime", "model", "backend"))
        )
    if full:
        build = record.get("build") or {}
        if any(build.values()):
            lines.append(f"build      {_pairs(build)}")
        target = record.get("target") or {}
        if any(value is not None for value in target.values()):
            lines.append(f"target     {_pairs(target)}")
        if evidence.get("signature"):
            lines.append(f"question   sig={evidence['signature']}")
    return lines


# --- the export ------------------------------------------------------------


def export(view: dict, read: dict, selector: str, out_dir: Path) -> dict:
    """One group, or one run, as a bundle safe to hand to somebody else."""
    terms = contract()
    groups = [
        group
        for group in view["groups"]
        if group["fingerprint"] == selector or selector in group["runs"]
    ]
    if not groups:
        raise TriageError(f"no failure group or run matches {selector!r}")
    group = groups[0]
    # Naming a run exports that run; naming a fingerprint exports its group.
    one_run = selector if selector in group["runs"] else None
    wanted = {one_run} if one_run else set(group["runs"])
    records = [record for record in group["records"] if record.get("run") in wanted]
    entries = [
        sanitize_entry(entry, terms)
        for entry in (read.get("entries") or [])
        if entry.get("run") in wanted
    ]
    bundle = {
        "record": "hawkes-failure-bundle",
        "exported_at": _when(round(time.time() * 1000)),
        "tool": "scripts/triage_hawkes_failures.py",
        "selector": selector,
        "contains": (
            "one failure group: its counts, its retained records, and whatever the "
            "diagnostic ring still holds for its runs. Shapes, counts, the page's "
            "own editor vocabulary and identifiers this profile minted. No question "
            "text, no answer text, no credentials, no screenshot."
        ),
        "group": {
            key: group[key]
            for key in (
                "fingerprint",
                "classification",
                "why",
                "count",
                "first_seen",
                "last_seen",
                "error_key",
                "outcome",
                "stopped_in",
                "editor_kind",
                "runs",
                "first_run",
                "markers",
                "generations",
                "runs_spanning_generations",
                "records_retained",
                "records_evicted",
            )
        },
        "records": [sanitize_record(record, terms) for record in records],
        "ring": entries,
        "allowlist": terms["safe_record_keys"],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(out_dir, 0o700)
    (out_dir / "failure-bundle.json").write_text(
        json.dumps(bundle, indent=2, default=str) + "\n", encoding="utf-8"
    )
    (out_dir / "summary.txt").write_text(
        report(view, detail=group["fingerprint"]) + "\n", encoding="utf-8"
    )
    for child in out_dir.iterdir():
        os.chmod(child, 0o600)
    return {"path": out_dir, "records": len(bundle["records"]), "ring": len(entries)}


# --- entry point -----------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", help="Profile directory; default is the newest.")
    parser.add_argument(
        "--file", help="A ledger JSON file, e.g. from an earlier export."
    )
    parser.add_argument("--group", help="Show one fingerprint in full.")
    parser.add_argument("--run", help="Show the group containing one run id, in full.")
    parser.add_argument("--export", dest="export_to", help="Bundle one group or run.")
    parser.add_argument(
        "--out", help="Where to write the bundle; default is a temp dir."
    )
    parser.add_argument("--json", action="store_true", help="The whole triage as JSON.")
    args = parser.parse_args(argv)

    try:
        read = read_ledger(args.profile, args.file)
        view = triage(read)
    except TriageError as error:
        print(f"triage refused: {error}", file=sys.stderr)
        return 1
    except Exception as error:  # noqa: BLE001 - an unreadable profile is a finding
        print(
            f"cannot read the ledger: {type(error).__name__}: {error}", file=sys.stderr
        )
        return 1

    if args.json:
        print(json.dumps(view, indent=2, default=str))
    else:
        # Exporting one group is asking about that group; printing the whole
        # ledger first would bury the thing being exported.
        print(report(view, detail=args.group or args.run or args.export_to))

    if args.export_to:
        out = (
            Path(args.out).expanduser()
            if args.out
            else Path(tempfile.mkdtemp(prefix="hawkes-failure-"))
        )
        try:
            written = export(view, read, args.export_to, out)
        except TriageError as error:
            print(f"export refused: {error}", file=sys.stderr)
            return 1
        print(f"\nbundle     {written['path']}")
        print(
            f"           {written['records']} record(s), {written['ring']} ring entries"
        )
        print(f"delete     rm -rf {written['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
