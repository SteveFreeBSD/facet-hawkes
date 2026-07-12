# Current Baseline

This is the known-good app and data baseline for `ethnos`. Host-specific
hardware, Ollama service settings, and benchmark results live in
[`PERFORMANCE_TUNING.md`](PERFORMANCE_TUNING.md) and [`hosts/`](hosts/).
System migration steps live in [`MIGRATION.md`](MIGRATION.md).
Suspicious answer inspection lives in [`TRACE_DEBUGGING.md`](TRACE_DEBUGGING.md).

For a CTO-facing rollup of repo shape, verification status, and remaining
hardening work, start with [`CTO_REVIEW.md`](CTO_REVIEW.md).

## What Works Now

- `ethics.pdf` is document `1`.
- `history.pdf` is document `2`.
- PDF ingestion works.
- 582 pages and 257 chunks exist in the current local database.
- `ethics.pdf` has 118 pages and 100 chunks. Section labels exist, with no
  unlabeled pages or chunks.
- `history.pdf` has 464 pages and 157 chunks. Section labels exist, with no
  unlabeled pages or chunks.
- Structured extraction is complete for both local documents: 257/257 chunks
  have valid latest model output.
- Normalized records are populated across the database: 257 chunk summaries,
  465 topics, 852 key terms, 390 examples, and 590 questions.
- `ethics.pdf` has 100 chunk summaries, 113 topics, 252 key terms, 74 examples,
  and 186 questions. Non-core ethics chunks have zero persisted key
  terms/questions; admin/support material is summary-only.
- `history.pdf` has 157 chunk summaries, 352 topics, 600 key terms, 316
  examples, and 404 questions. Non-core history chunks have zero persisted key
  terms/questions; admin/support material is summary-only.
- `ask` works with local Ollama retrieval context.
- `chat` works with the same retrieval and answer path.
- `ask` and `chat` support opt-in Agentic Q&A with local-PDF search/inspect
  tools, quiet terminal output, trace details when requested, and fixed Q&A
  fallback.
- `ask` and `chat` can write local JSON traces with `--trace-dir`.
- `inspect-trace` summarizes local answer traces without calling Ollama.
- Comparison-aware retrieval works for retrieval-only benchmark cases.
- Chat follow-up and continuation context is covered by regression tests.
- Mixed quiz benchmarks atomically checkpoint after every item and can resume
  compatible interrupted runs.
- Mixed quiz benchmarks support targeted `--item-id` subsets and retain bounded
  consistency-retry attempts and reasons in their reports.
- Validated quiz anchors are authoritative model context; retrieval candidates
  remain diagnostic rather than polluting anchored prompts.
- Compound choice guidance covers “All of the above” and Canvas “All possible
  answers” variants only when each individual option is source-supported.
- Disputed instructor keys are audited separately and excluded from
  PDF-grounded accuracy without being hidden from instructor-key agreement.

## Working Model

The chosen working model for now is `gemma-python`, with thinking disabled by
default. Current defaults are:

- `ETHNOS_OLLAMA_STRUCTURE_NUM_PREDICT=2048`
- `ETHNOS_OLLAMA_ANSWER_NUM_PREDICT=1536`
- `ETHNOS_OLLAMA_NUM_CTX=8192`
- `ETHNOS_OLLAMA_THINK=false`
- `ETHNOS_OLLAMA_NUM_THREAD` unset

`ETHNOS_OLLAMA_THINK=auto` can be used to omit the `think` request field when
testing another model or Ollama build. The app also accepts `true`, `low`,
`medium`, and `high` for current Ollama Python clients, but those are not the
review baseline.

## Verification Snapshot

Observed on 2026-06-27:

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed.
- `uv run python -m compileall -q src tests`: passed.
- `uv run pytest -q`: full suite passed.
- `uv run vulture src tests --min-confidence 80`: clean and enforced in CI.

Last recorded model-backed checks, not rerun during the 2026-06-27
deterministic hardening pass:

- CPU-local Agent Review probe for `history_ch20_canvas.json`:
  `20` keyed answers supported, `17` pass items, `3` inspect items, and the
  duplicate prompt plus `Temperence` quality findings preserved.
- `uv run ethnos ask 1 "What is virtue ethics?" --limit 2 --num-predict 256 --debug-ollama`:
  retrieved core chunks 31, 32, and 39; Ollama returned a cited answer with
  `done_reason=stop`, no hidden thinking, and no API error.

The current MC-only benchmark default is `mc-bench --chars 300`, with
`ETHNOS_OLLAMA_NUM_CTX=8192` and `ETHNOS_OLLAMA_NUM_THREAD` unset. The value is
based on the measured `caspian` benchmark ladder in the performance guide.
Mixed `quiz-bench` still uses `--chars 900` for essay drafts and broader answer
context. It performs one bounded consistency retry by default; repeat
`--item-id` for cheap follow-up runs or use `--answer-retries 0` for a strict
one-call timing baseline.

Host-level performance profile on `caspian` as of 2026-07-11:

- Ollama 0.31.1 with `OLLAMA_KEEP_ALIVE=24h`, flash attention, mlock, and
  memlock infinity.
- `vm.min_free_kbytes=262144`.
- `scx_bpfland` Auto through enabled `scx_loader.service`.
- CPU governor remains `schedutil`.
- Current MC timing reference:
  `data/runs/perf-caspian-bpfland-auto-repeat-20260711-mc.json`, 20/20,
  38.947 seconds, zero invalid responses, zero no-context cases.
- Mixed validation:
  `data/runs/perf-caspian-bpfland-mixed-warm-20260711.json`, 19/20 grounded
  accuracy, zero invalid responses, zero no-context cases.
- Reboot validation on 2026-07-11 confirmed `scx_bpfland` Auto,
  `vm.min_free_kbytes=262144`, and the Ollama 24-hour keepalive profile all
  returned after restart.

The structure prompt is intentionally compact. Schema `title` metadata is kept
because removing it caused Gemma to omit required example fields in smoke tests.

## Local Data Inventory

`data/` is intentionally ignored by git, so this runtime state must be copied or
rebuilt during migration:

- `data/ethnos.sqlite`: about 11 MiB, contains both processed documents.
- `data/incoming/ethics.pdf`: about 1.9 MiB, SHA prefix `eac21ab05849`.
- `data/incoming/history.pdf`: about 6.9 MiB, SHA prefix `81ad69f0b520`.

There are 28 extraction runs in the current database. Every chunk's latest
output is valid.

## Review Checklist

Use this list when validating a host or reviewing a change set:

- Confirm the host inventory snapshot is current (Ollama version, installed
  models, service override, kernel, governor, swap).
- Confirm service overrides include flash attention, mlock, and memlock
  infinity, plus keep-alive on benchmark hosts.
- Confirm the working model defaults match the baseline in
  `docs/PERFORMANCE_TUNING.md`.
- Run the baseline MC and mixed quiz benchmarks (`mc-bench --chars 300` and
  `quiz-bench --chars 900`) and save reports under `data/runs/`.
- Run the smoke checks below and compare against the expected outputs.

## Smoke Checks

These checks are deterministic or read-only and safe for baseline verification:

```bash
uv run python -m compileall -q src tests
uv run pytest -q
uv run ethnos documents
uv run ethnos db-info
uv run ethnos section-status 1
uv run ethnos structure-status 1
uv run ethnos quality-report 1
uv run ethnos section-status 2
uv run ethnos structure-status 2
uv run ethnos quality-report 2
uv run ethnos qa-bench 1 --benchmark benchmarks/ethics_qa.json --no-ask
git status --short
```

## Expensive Commands To Run Intentionally

These mutate processed data or perform long model runs. Run them only when
their cost and output location are intentional:

```bash
uv run ethnos qa-bench 1 --benchmark benchmarks/ethics_qa.json --ask
uv run ethnos structure 1 --force
uv run ethnos structure 1 --retry-failed
uv run ethnos structure 1 --all-roles
```

Long Ollama benchmarks, multi-model comparisons, PDF re-extraction, and
structured re-extraction should always write inspectable outputs under
`data/runs/`.

## Local Database Recovery

`data/ethnos.sqlite` is ignored local runtime state. Deleting or replacing it
does not delete the source code, but it does remove the local processed
database. The source PDFs for the current baseline are
`data/incoming/ethics.pdf` and `data/incoming/history.pdf`.

To recover from a missing, corrupted, or intentionally replaced database,
recreate `ethics.pdf` from the source PDF:

```bash
uv run ethnos ingest-pdf data/incoming/ethics.pdf
uv run ethnos chunk 1
uv run ethnos label-sections 1 --preset ethics
uv run ethnos structure 1 --all-roles
```

The `structure` step is expensive because it calls Ollama. The baseline keeps
valid model outputs and summaries for every chunk, so exact recovery uses
`--all-roles`; normalized key terms/questions are still persisted only for core
chunks. Omit `--all-roles` when you intentionally want a cheaper core-only
rebuild. Do not run long structure passes during baseline stabilization unless
the rebuild is intentional.

`history.pdf` can be rebuilt the same way:

```bash
uv run ethnos ingest-pdf data/incoming/history.pdf
uv run ethnos chunk 2
uv run ethnos label-sections 2 --preset history
uv run ethnos structure 2 --all-roles
```

If a document was structured before section labels were applied, run
`uv run ethnos refresh-records <document_id>` after labeling to rebuild
normalized records according to the current content roles.

To back up the current processed database manually, copy
`data/ethnos.sqlite` to another file under `data/` or to a location outside the
repo. Database backups should stay ignored local data and should not be
committed.

## Next Sensible Project Areas

- Add an explicit multiple-response quiz type with list-valued answer keys and
  set-based scoring before accepting Canvas “select two/all” items.
- Add retrieval-confidence thresholds or chapter bounds for unanchored quiz
  candidates.
- Add a single orchestration command for import, validation, grounding,
  benchmark, and key audit.
