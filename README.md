# Facet Hawkes Assistant

<p align="center">
  <img src="extension/icons/icon-128.png" width="96" height="96" alt="Facet Hawkes Assistant icon">
</p>

<p align="center"><strong>A local-first Firefox assistant built for Hawkes math.</strong></p>

This is the canonical repository for **Facet Hawkes Assistant**: the Firefox
add-on, its local companion, and the supporting study and quiz tooling. The
Python package and installed compatibility identifiers retain the name
`ethnos`; the product shown in Firefox is Facet Hawkes Assistant.

It turns a Hawkes question into a checked, ready-to-place answer without
handing the page to a cloud service. Focus the answer box, open the add-on, and
review what it read alongside what it solved. One separate click places the
answer using Hawkes' own math editor. **You stay in control: it never submits,
checks, advances, or silently selects anything.**

[![CI](https://github.com/SteveFreeBSD/facet-hawkes/actions/workflows/ci.yml/badge.svg)](https://github.com/SteveFreeBSD/facet-hawkes/actions/workflows/ci.yml)

## The Firefox add-on

The add-on is **Facet Hawkes Assistant**, currently **0.46.0**. It combines a
narrow Firefox interface with a local Python companion, Facet's own solver
routing, and an image fallback for a question the page draws as a picture:

- **Exact before AI.** The add-on reads Hawkes' MathML and hands it to Facet,
  which routes factoring, expansion, simplification, rationalization,
  evaluation, polynomial ordering, degree, coefficients, and classification
  through SymPy before any model is considered. Results are checked
  algebraically and typically arrive in milliseconds.
- **See what it saw.** The panel puts the recognized problem beside the answer.
  Screenshot fallbacks use two different local readers and disable insertion
  when they disagree about a sign, exponent, radical, or fraction.
- **Native math entry.** Fractions, radicals, exponents, absolute values, and
  tested combinations are assembled with Hawkes' own keypad templates instead
  of pasted as ambiguous punctuation.
- **A deliberate second click.** Solving never means submitting. Answers are
  inserted only after review, only into the field you focused, and never into a
  different tab, frame, window, or changed question.
- **Local by design.** The browser package contains no network client. It talks
  through Firefox native messaging to one registered companion process; keep
  Ollama on loopback and the whole solve stays on your machine.
- **No injected interface.** The toolbar panel and Settings are Firefox pages,
  so the add-on leaves no persistent UI, styles, markers, or listeners in the
  Hawkes page. Its synthetic insertion events can still be observed; the add-on
  does not claim or attempt concealment.

### New in 0.45.0: the question's own table

A Hawkes word problem states its data in a table with a heading over each
column. The add-on now reads that table *as a table* — headings and cells,
exactly as the page wrote them — alongside the MathML and the plotted points it
already read, and the host names the columns from the question's own words
("treating revenue as a function of the number of photos sold") rather than
from their order.

That is what makes lesson 3.3's revenue question exact. Three rows, a quadratic
regression, and "what number of photos sold and what price per photo will
maximize her revenue?" resolve to **9 photos at $36** in about forty
milliseconds and with no model call: Facet fits `y = -4x² + 72x` over exact
rationals, turns it at x = 9, and reports 324/9 as the price. Before either
number is offered for insertion the host proves all of it against its own
reading of the table — the rows multiply out, the table agrees with the plotted
points, the coefficients satisfy the exact least-squares normal equations, the
turning point is where that curve turns, and 36 × 9 = 324.

### New in 0.44.0: one solver, named on the tin

The add-on is **Facet Hawkes Assistant**. Facet owns solver routing end to end
— exact mathematics first, a reasoning model only for what those decline, and
the parabola and quadratic-regression specialists for a graph — so the Settings
choice between "Ethnos only" and "Ethnos, then Facet" is gone. It described a
division of labour that no longer exists, and a preference left over in an
upgraded profile is removed rather than honoured. A question the page draws as
a picture rather than stating as mathematics is still read from an image by the
companion.

### New in 0.46.0: the answer becomes a score

**One deterministic score drives all four things at once** — when each character
is typed, when the playhead moves, what the panel says, and what you hear. There
is no second clock anywhere in the feature. A note exists because a character was
accepted; if Hawkes refuses one, the music stops with it.

**Answer Cadence** previews a structured equation in Settings with Classical,
Jazz, Lo-fi, Electronic or Custom arrangement. These are five readings of the
same score, not one sound with the waveform changed: each has its own mode,
chord voicings, register plan, instrument, envelopes, percussion and cadence,
and the mathematics chooses the notes — a digit takes the degree of its value, a
letter keeps one pitch throughout an answer, an operator turns the harmony, an
exponent lifts an octave, a denominator drops one. Changing arrangement moves no
timestamp. Tempo and the 2–12 second window are separate controls, and changes
stay a draft until **Apply cadence**.

Building a fraction or an exponent takes the editor real time the score never
allotted, so the phrase is *held* while it happens and resumes in tempo, rather
than dumping every remaining note at once. Across fifteen answers entered into
real Hawkes, each character landed within 1–11 ms of its own score offset, drift
across a whole answer stayed between −4 and +5 ms, and every note sounded 8–38 ms
after the character that caused it — including the answers where the editor held
the phrase for a quarter of a second to build a template.

Volume, mute and music during insertion are all in Settings; insertion music is
off unless you turn it on. The local Web Audio instrument lives in the event
page and receives finite, one-way cues. There are no new permissions, samples,
models or network dependencies, and the whole feature adds 11.1 KB to the package
and no measurable CPU beyond what entering the same answer costs in silence.
Existing Hawkes safety checks and graph actions remain in their established
paths; synthetic input and transient presentation cues are observable to page
code. Read the [Answer Cadence design note](docs/ANSWER_CADENCE.md) for
architecture, Firefox lifecycle, sound design, measurements and the NPU
assessment.

### The workflow

1. Focus the Hawkes answer field and open the add-on with `Alt+Shift+E`.
2. Let Facet's exact solvers answer immediately, or wait for reasoning, a graph
   specialist, or the image fallback when the page does not expose enough
   structured math.
3. Compare **Recognized problem** with the question on screen.
4. Click **Insert answer**. Review the field, then decide what to do in Hawkes.

The add-on fails closed when it cannot identify one safe target, when the
question changes mid-solve, when two screenshot readers disagree, or when the
answer needs an editor template Hawkes has not enabled.

Nothing has to be watching for those. A run that fails, is refused, or produces
an answer the editor will not take leaves one bounded, redacted record behind,
and one offline command reads them back grouped by fault:

```bash
python3 scripts/triage_hawkes_failures.py
```

The ledger holds no question text, no answer text and no screenshot; it is
capped at 40 records, 64 groups, 14 days and 96 KB, evicts the oldest by
itself, and **Settings -> Diagnostics -> Clear** erases it along with the log.
See [Retained failure ledger](docs/FAILURE_LEDGER.md).

### Install and verify

Firefox 142 or newer, Python 3.11+, `uv`, and a local Ollama installation are
required. The 0.46.0 source layout uses two sibling repositories, with
`facet-runtime` fixed at companion commit
`f2e09071415907cbbe1b4b905af9af6473098e8b`:

```bash
git clone https://github.com/SteveFreeBSD/facet-hawkes.git
git clone https://github.com/SteveFreeBSD/facet-runtime.git
git -C facet-runtime checkout --detach f2e09071415907cbbe1b4b905af9af6473098e8b
cd facet-hawkes
```

Install the locked Python environment and register the native companion:

```bash
uv sync --frozen --extra dev
python3 deploy/firefox/install_native_host.py --write
python3 deploy/firefox/install_native_host.py --check
```

Normal Firefox requires a Mozilla-signed XPI. Follow the
[release and installation runbook](extension/RELEASE.md) for signing,
installation, physical acceptance, and rollback; do not disable Firefox's
signature enforcement. For the complete behavior, permissions, privacy model,
settings, and exact-operation table, read the
[add-on guide](extension/README.md).

Use assistance tools only where they are permitted.

## The local study engine

The same local companion is a full study and review system for PDF course
material. It ingests PDFs, builds searchable structured knowledge, answers
questions from retrieved source text, imports and audits quizzes, benchmarks
local models, and produces evidence-backed Agent Review reports.

All course data stays local by default. SQLite stores the processed knowledge,
PyMuPDF reads PDFs, SymPy handles exact mathematics, and Ollama runs the local
models.

## Current supported baseline

The host is `casbox` (Ryzen AI HX 370, Radeon 890M), with Ollama on loopback:

- Text and agent work: `qwen3.5:9b`.
- Image questions: `qwen3.5:4b` read first, `qwen3.5:9b` as the independent
  second reader. Two *different* models on purpose, so one cannot merely repeat
  its own symbol mistake.
- Ethnos context: `4096` tokens, thinking disabled, thread count unset.
- Exact mathematics and solver routing are Facet's, not a model's; see
  [docs/FACET_BRIDGE.md](docs/FACET_BRIDGE.md).
- Facet runs on this same machine, reached by running `facet-remote` as a local
  subprocess. Nothing in a solve crosses a network.

The earlier baseline ran on the HP t740 named `caspian`, against a model alias
that exists only on that machine and predates this setup. Its fixed MC
acceptance figure was measured there and is not restated here, because it says
nothing about the models above: the acceptance benchmark needs re-running before
any number is quoted as current.

These are operating defaults, not generic recommendations for every machine.
See [Current Baseline](docs/CURRENT_BASELINE.md) and the
[Caspian host profile](docs/hosts/caspian.md) for evidence and verification.

## Install

Requirements:

- Python 3.11 or newer
- `uv`
- SQLite with FTS5
- Ollama with `qwen3.5:9b`; screenshot questions additionally use `qwen3.5:4b`

Install the Python environment:

```bash
uv sync --extra dev
```

Verify the checkout and local model:

```bash
uv run pytest -q
uv run ruff check .
ollama show qwen3.5:9b
```

The application has working defaults in code. `.env.example` is only a
template; Ethnos does not load `.env` automatically. To use a local environment
file, pass it to `uv`:

```bash
cp .env.example .env
uv run --env-file .env ethnos documents
```

For a new machine, follow the complete [Migration Checklist](docs/MIGRATION.md),
including Ollama service and model-alias setup.

## First run

If the processed database was copied with the checkout, verify it without
calling Ollama:

```bash
uv run ethnos documents
uv run ethnos db-info
uv run ethnos section-status 1
uv run ethnos structure-status 1
uv run ethnos qa-bench 1 --benchmark benchmarks/ethics_qa.json --no-ask
```

Then run one read-only model smoke test:

```bash
uv run ethnos ask 1 "What is virtue ethics?" --limit 2 --debug-ollama
```

Expected: `qwen3.5:9b`, context `4096`, no hidden thinking, and `ollama ps`
reporting the model resident on the GPU.

## Add a PDF

```bash
uv run ethnos ingest-pdf path/to/course.pdf
uv run ethnos chunk DOCUMENT_ID
uv run ethnos label-sections DOCUMENT_ID --preset ethics
uv run ethnos structure DOCUMENT_ID --limit 1 --debug-ollama
uv run ethnos structure DOCUMENT_ID
```

Use `--preset ethics` for `ethics.pdf`, `--preset history` for `history.pdf`,
and `--preset precalc` for the 1,094-page Stitz-Zeager corrected edition. For
another book, inspect and label its sections before a full structure run. The
one-chunk smoke prevents an expensive run with a broken model or prompt.

`structure` processes core or unlabeled chunks that do not already have valid
output. Use `--retry-failed` for failed chunks, `--all-roles` when summaries are
required for admin/support material, and `--force` only for an intentional full
reprocessing pass.

## Search and inspect

```bash
uv run ethnos search "evolutionary ethics" --role core
uv run ethnos context 1 "methodological ethical naturalism" --limit 3
uv run ethnos inspect-chunk 1 80 --records
uv run ethnos inspect-page 1 45
uv run ethnos records 1 --type key_terms --role core --limit 10
uv run ethnos quality-report 1
```

`section_label` describes the PDF section. `content_role` groups sections as
`core`, `support`, `admin`, `artifact`, or `unknown`. Retrieval defaults to
`core` so references, licensing, and front matter do not dilute study answers.

## Ask and chat

```bash
uv run ethnos ask 1 "What is methodological ethical naturalism?"
uv run ethnos ask 1 "What is virtue ethics?" --trace-dir data/runs
uv run ethnos chat 1 --trace-dir data/runs
```

Render a grounded answer as a shareable PNG with the symbol-specific keyboard
and LaTeX commands included in the image and written to a copyable companion
file:

```bash
uv run ethnos ask 3 "Solve the equation shown in section 6.4" \
  --model precalc-local \
  --answer-image data/runs/precalc-answer.png
```

This creates `precalc-answer.png` and `precalc-answer.keys.txt`. Image rendering
uses the local `pango-view` command and does not make an additional model call.

For a photographed or screenshotted question, the default pipeline uses
Qwen3.5 and an independent Gemma verification pass before the math solver:

```bash
uv run ethnos ask 3 "Solve the attached problem" \
  --question-image path/to/problem.png \
  --answer-image data/runs/precalc-answer.png
```

On the KDE desktop, Ethnos can perform the safe capture handoff itself:

```bash
uv run ethnos ask 3 "Solve the pictured problem" --capture-question
```

Drag a rectangle around only the question panel. Ethnos saves that region,
performs the same two-reader verification and exact-math routing, writes an
answer-only PNG plus a complete trace beside the capture, and opens the PNG in
the desktop image viewer. The PNG contains only the answer in visual form,
including stacked fractions and radical symbols; no directions, sources, or
separate symbol-key file are produced. Files are stored under
`data/runs/captures/`. This invokes Spectacle only; it does not attach to,
navigate, restart, or modify the browser.

The vision stage preserves expressions, answer choices, graph/diagram details,
interface metadata, and explicit reading uncertainties. Two different readers
must agree before solving. Scoreboard counters are excluded from answer choices.
Exact polynomial factor/expansion questions take a safe SymPy-backed,
zero-token path; other image problems use compact structured output from
`qwen3.5:4b`. Screenshot answers render as concise answer-only
cards. Use `--accept-image-uncertainty` only after manually checking the
printed transcription. Identical screenshots reuse a content-addressed
two-reader transcription cache; use `--no-question-image-cache` to force a
fresh read.

See [Vision and Exact-Math Architecture](docs/VISION_MATH_ARCHITECTURE.md) for
model evidence, exact settings, acceptance requirements, and rollback commands.

Add `--agentic` when the model should iteratively search and inspect local PDF
evidence before answering:

```bash
uv run ethnos ask 1 "Compare virtue ethics and utilitarianism" \
  --agentic --trace-dir data/runs
```

The fixed one-retrieval/one-call path remains the speed and compatibility
baseline. Agentic Q&A falls back to it if the bounded tool loop cannot finish.
See [Agentic Q&A](docs/AGENTIC_QA.md) and
[Trace Debugging](docs/TRACE_DEBUGGING.md).

## Quiz workflow

Generate and benchmark a source-grounded MC quiz:

```bash
uv run ethnos generate-quiz 1 \
  --source terms \
  --difficulty medium \
  --limit 20 \
  --seed 42 \
  --output data/runs/quiz.json

uv run ethnos mc-bench 1 \
  --quiz data/runs/quiz.json \
  --chars 300 \
  --output data/runs/mc-report.json
```

For Canvas/LMS imports, mixed MC/true-false/essay quizzes, source anchors,
answer-key audits, retries, checkpoint/resume, and report interpretation, use
the single [Quiz Workflow](docs/QUIZ_WORKFLOW.md). Prefer the generic
`review-quiz`, `validate-quiz`, and `quiz-bench` commands for mixed quizzes.
The MC-specific commands remain useful for controlled performance comparisons.

## Agent Review

```bash
uv run ethnos agent-review 2 \
  --quiz benchmarks/history_ch20_canvas.json \
  --output data/runs/history_ch20_agent_review \
  --model qwen3.5:9b \
  --profile cto \
  --vision-pages off \
  --debug-agent
```

The output directory contains a Markdown review, structured JSON, and an
optional tool trace. See [Agent Review](docs/AGENT_REVIEW.md) for verdicts,
evidence strength, priorities, and model profiles.

## Export and maintenance

```bash
uv run ethnos export-markdown 1 --output data/processed/ethics.md
uv run ethnos export-study 1 --output data/processed/study-guide.md
uv run ethnos export-json 1 --output data/processed/ethics.json
uv run ethnos rebuild-fts
uv run ethnos refresh-records 1
```

`refresh-records` rebuilds normalized rows from valid stored model outputs and
does not call Ollama. `rebuild-fts` repairs the local search index.

## Data and safety

The default database is `data/ethnos.sqlite`. PDFs, the database, traces,
exports, and benchmark reports under `data/` are ignored by Git. Back them up
or copy them separately during migration.

Cheap/read-only commands:

```bash
uv run ethnos documents
uv run ethnos db-info
uv run ethnos section-status 1
uv run ethnos structure-status 1
uv run ethnos quality-report 1
uv run ethnos qa-bench 1 --benchmark benchmarks/ethics_qa.json --no-ask
```

Potentially expensive or mutating commands include PDF ingestion, chunking,
`structure`, model-backed benchmarks, and multi-model comparisons. Write their
reports under `data/runs/` and start with a one-item smoke.

## Development checks

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run python -m compileall -q src tests
uv run vulture src tests --min-confidence 80
```

## Documentation

Start with the [Documentation Index](docs/README.md). The authoritative current
documents are:

- [Current Baseline](docs/CURRENT_BASELINE.md): known-good app, data, model,
  and benchmark state.
- [Pre-calculus Setup](docs/PRECALCULUS.md): math model, benchmark, and course
  ingestion workflow.
- [Performance Tuning](docs/PERFORMANCE_TUNING.md): benchmark protocol,
  measured decisions, and rejected experiments.
- [Host profiles](docs/hosts/README.md): which machine runs what. One does:
  `casbox` is the browser machine, the native-host machine and the Facet
  runtime host at once. [Caspian](docs/hosts/caspian.md) is the historical
  benchmark host and its hardware notes.
- [Migration Checklist](docs/MIGRATION.md): reproduce the system elsewhere.
- [The Ethnos-Facet boundary](docs/FACET_BRIDGE.md): the protocol, its
  security properties, and how the transport is configured.
- [Ollama Troubleshooting](docs/OLLAMA_TROUBLESHOOTING.md): model, Vulkan,
  response, and stability failures.
- [Live Hawkes Observatory](docs/LIVE_OBSERVATORY.md): one correlated look at
  the live session, from one clock.
- [Retained failure ledger](docs/FAILURE_LEDGER.md): what a failure leaves
  behind when nobody was watching, and how to triage it afterwards.
