# Retained failure ledger

Use Hawkes normally, with nothing watching. When a run ends badly the add-on
keeps one bounded record of it. Later, an agent runs one command and sees the
real failures grouped by fault:

```console
$ python3 scripts/triage_hawkes_failures.py
```

Firefox does not have to be running. Nothing in that command touches the
session.

## Why this exists

The [Live Hawkes Observatory](LIVE_OBSERVATORY.md) answers "what is happening
now", and answering it needs the session to still be there. That was the one
thing it could not solve. The diagnostic ring holds two hundred entries shared
by every context and a single solve costs a dozen of them, so the entries that
explain a refusal are pushed out by ordinary use within the hour — and the
evidence that has actually diagnosed live failures, the editor's own
description of itself, was recorded only at `debug`, which is off.

Both of those meant the same thing in practice: to triage a failure, a
high-reasoning agent had to be attached to the browser when it happened. That
is a vigil, not a diagnostic. The owner cannot work while one is running, and
the failures worth finding are the ones that happen on an ordinary afternoon.

## What is retained, and when

A run is retained when it reaches a terminal state that is explicitly
diagnostic. There are three, and `background.js` reaches them by exactly three
calls to `retain`:

| Outcome | Reached when |
|---|---|
| `failed` | `fail()` — every failure in the add-on passes through it, including a companion refusal and a settings-page health check that got no answer |
| `not-insertable` | A solve produced an answer this editor will not take. The panel shows it, Insert stays disabled, nothing presses anything — the ring used to record a clean solve followed by silence |
| `disputed` | The reading of the question was disputed, so the answer may not be to the question on screen |

A successful run writes nothing. A record per solve would be a log rather than
a ledger, and it would spend the bound on successes on its way to pushing the
failures out.

Each record holds what the event page was already holding at that moment,
never a re-read of the log:

- the run id, the event page's generation, and the wall-clock time;
- the outcome, the error key, the refusal label, the phase and the stage it
  stopped in, and the full stage trail;
- the window, tab, frame and field count it was about;
- **the complete editor description** — kind, whether it was readable, whether
  it is even typeable, maximum length, the character set it accepts, the
  templates it offers, its keypad slots, and one of these per control for a
  multi-field question;
- what the add-on could read of the question: exact markup or a refused
  reading, how many expressions, whether there was a graph or a table, the
  prompt's length, and the question's digest;
- Facet's route and the runtime, model, backend and device that answered;
- the native-host request ids this run used, which are `<run>.<n>`;
- the solve that produced the answer, when this is an insertion failing on
  someone else's work;
- the answer's shape — a length, a part count, and what each entry route said
  — and never the answer;
- the build marker and version it happened on.

## The fingerprint

Every record carries `f1:<sixteen hex characters>`, folded from the fields two
occurrences of one fault have in common: the outcome, the error key, the
refusal, the phase, the stage trail, the editor's kind, count, enabled state,
templates and character sets, what was readable of the question, Facet's route,
the runtime, and what each entry route said about the answer.

Deliberately not folded in: run ids, generations, timestamps, elapsed times,
window/tab/frame ids, the question's digest, its prompt length, its expression
count, the answer's length, and the build marker. Every one of those changes
between two instances of one fault, and any of them would produce a ledger of
forty groups of one — which is the thing the ledger exists to stop.

The build marker is recorded on the group instead, so "still happening on the
build that was meant to fix it" stays answerable.

`f1` names the rules the fingerprint was folded from. Change those and the same
fault gets a new name; the triage report says so rather than reporting one
problem as two.

## Records and groups

Two structures, with different jobs.

**Records** hold the detail and are evicted first. **Groups** hold the count,
the first and most recent run ids, every build and event-page lifetime the
fault has appeared in, and the traits offline classification needs — so *this
has now happened eleven times* survives long after the eleven records have
gone. The group cap is deliberately larger than the record cap for that reason.

## Bounds and automatic cleanup

Enforced on every write, oldest first, in this order:

| Bound | Value | Declared in |
|---|---|---|
| Records | 40 | `MAX_RECORDS` |
| Groups | 64 | `MAX_GROUPS` |
| Age | 14 days | `MAX_AGE_MS` |
| Size | 96 KB serialized | `MAX_BYTES` |

Age first — an expired record is worthless whatever the count is. Then count.
Then size, which drops the oldest surviving records until the whole ledger
fits; it is the backstop for a record that is unusually large, and in ordinary
use the count binds first.

The ledger keeps cumulative counters of what it let go, by age, by count and by
size, and the triage report prints them. Cleanup happens when a failure is
written, so a ledger that stops receiving failures stops changing — it is
already within every bound at that point. **Settings → Diagnostics → Clear**
erases the ledger along with the ring, and the entry count is shown there so
this is not storage the user cannot see.

## Privacy

The [privacy notice](../extension/PRIVACY.md) is authoritative. In short:

- Question text, answer text, credentials and screenshots are never stored, at
  any level, in any mode. Every field of a record is built by name and filtered
  again through `SAFE_RECORD_KEYS`, so a call site that hands the recorder more
  than it should stores nothing extra.
- What the student has typed into the answer box is part of the page's editor
  model and is specifically not read. What the *page* says about its own
  control — the characters it accepts, the templates it offers — is, because
  that is what diagnoses a refused insertion, and it is not anyone's work.
- Screenshots remain explicit and on demand: `observe_live_hawkes.py
  --screenshot --bundle`, which prints its own `rm -rf`. Nothing in this path
  can take one; the triage tool runs no command at all.
- An exported bundle is filtered a second time, through the add-on's own
  allowlist and `common/log.js`'s own list of what counts as coursework, so a
  hand-edited profile still cannot put an answer into a file meant to be
  shared.

## Lifecycle neutrality

Writing a record must not change what the browser was going to do:

- **It starts nothing.** No timer, no alarm, no port, no message — the four
  things that wake or hold open a suspended event page. It is one storage
  write in response to something that has already happened.
- **It is never awaited.** The panel has already been told; a diagnostic must
  not sit in front of the user being told, and an operation must not be able to
  fail because storage did.
- **It reads no page.** Every field comes from state the event page already
  held. Nothing goes back to the tab for more.
- **Reading it writes nothing.** The triage tool opens a copy of the profile
  database and never connects to the add-on.

`tests/test_hawkes_failure_ledger.py` asserts each of these, including against
the shipped `background.js`.

## The triage report

```console
$ python3 scripts/triage_hawkes_failures.py
$ python3 scripts/triage_hawkes_failures.py --group f1:ce992b2738bf1098
$ python3 scripts/triage_hawkes_failures.py --run r2f8xk91c4
$ python3 scripts/triage_hawkes_failures.py --export f1:ce992b2738bf1098
$ python3 scripts/triage_hawkes_failures.py --json
```

Groups are ordered by how often they have happened, so the highest-value root
cause is first, and are printed under the failure class they belong to. Those
eight classes are the observatory's own, declared once in
`observe_live_hawkes.py` with the evidence that puts a run in each — a bundle
and an observation can never disagree about what kind of failure a run was.

Each group prints its count, when it last happened, the error key, the stage
trail, the complete editor description, what was readable, the route and
runtime, its representative run ids, every build it has appeared on, and how
much of itself is still retained. Where the diagnostic ring still holds entries
for one of those runs, they are joined back by run id and counted — and a run
whose ring entries span two event-page lifetimes is named as one that outlived
its own event page. That is a fact about the run, not about the group: six
occurrences recorded across two lifetimes is not one run that spanned two, and
reading it as one would report a fault that is not there.

## The export

```console
$ python3 scripts/triage_hawkes_failures.py --export f1:ce992b2738bf1098
```

Writes `failure-bundle.json` and `summary.txt` into a `0700` directory as
`0600`, and prints the command that deletes it. Naming a run rather than a
fingerprint exports that run alone.

The bundle carries the group, its retained records, and whatever the ring still
holds for its runs — everything sanitized on the way out, and the allowlist it
was sanitized against included so a reader can check. If that allowlist cannot
be read out of the add-on's source, the export is refused rather than guessed
at.

## What still needs a live session

- Which build Firefox is *currently* running. A record names the build it
  happened on; only `observe_live_hawkes.py` can compare that with the working
  tree.
- A picture of the question. Coursework, on demand, and deleted after reading.
- Anything about a run that failed without reaching a terminal state at all —
  a run still in flight is not a retained failure.
- A run that outlived its own event page leaves no record: the page that would
  have written it is the one that went away. The ring shows it for as long as
  it holds the entries, and the triage report names it.

## See also

- [Live Hawkes Observatory](LIVE_OBSERVATORY.md) — one correlated look at the
  session as it is now
- [Hawkes live findings](HAWKES_LIVE_FINDINGS.md) — what live testing exposed
- [Hawkes privacy notice](../extension/PRIVACY.md) — what is stored, and where
