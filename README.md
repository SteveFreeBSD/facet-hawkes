# Ethnos

Ethnos is a local-first study and review system for PDF course material. It
ingests PDFs, builds searchable structured knowledge, answers questions from
retrieved source text, imports and audits quizzes, benchmarks local models, and
produces evidence-backed Agent Review reports.

All course data stays local by default. SQLite stores the processed knowledge,
PyMuPDF reads PDFs, and Ollama runs the language model.

## Current supported baseline

The primary host is the HP t740 named `caspian`:

- CachyOS with an AMD Ryzen Embedded V1756B, 64 GiB RAM, and Vega 8 graphics.
- Ollama `0.32.1` using Vulkan/RADV.
- Required model: `gemma-python`.
- Ethnos context: `4096` tokens, thinking disabled, thread count unset.
- Ollama reports Gemma at `100% GPU`; all 36 model layers are offloaded.
- Fixed MC acceptance benchmark: 20/20 correct in 118.1 seconds, including a
  cold model load.

These are operating defaults, not generic recommendations for every machine.
See [Current Baseline](docs/CURRENT_BASELINE.md) and the
[Caspian host profile](docs/hosts/caspian.md) for evidence and verification.

## Install

Requirements:

- Python 3.11 or newer
- `uv`
- SQLite with FTS5
- Ollama with the `gemma-python` model alias

Install the Python environment:

```bash
uv sync --extra dev
```

Verify the checkout and local model:

```bash
uv run pytest -q
uv run ruff check .
ollama show gemma-python
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

Expected on `caspian`: `gemma-python`, context `4096`, no hidden thinking, and
`ollama ps` showing `100% GPU`.

## Add a PDF

```bash
uv run ethnos ingest-pdf path/to/course.pdf
uv run ethnos chunk DOCUMENT_ID
uv run ethnos label-sections DOCUMENT_ID --preset ethics
uv run ethnos structure DOCUMENT_ID --limit 1 --debug-ollama
uv run ethnos structure DOCUMENT_ID
```

Use `--preset ethics` for `ethics.pdf` and `--preset history` for
`history.pdf`. For another book, inspect and label its sections before a full
structure run. The one-chunk smoke prevents an expensive run with a broken
model or prompt.

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
  --model gemma-python \
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
- [Performance Tuning](docs/PERFORMANCE_TUNING.md): benchmark protocol,
  measured decisions, and rejected experiments.
- [Caspian](docs/hosts/caspian.md): live hardware and persistent host settings.
- [Migration Checklist](docs/MIGRATION.md): reproduce the system elsewhere.
- [Ollama Troubleshooting](docs/OLLAMA_TROUBLESHOOTING.md): model, Vulkan,
  response, and stability failures.
