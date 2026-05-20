# Current Baseline

This is the known-good app and data baseline for `ethnos`. Host-specific
hardware, Ollama service settings, and benchmark results live in
[`PERFORMANCE_TUNING.md`](PERFORMANCE_TUNING.md) and [`hosts/`](hosts/).
System migration steps live in [`MIGRATION.md`](MIGRATION.md).

## What Works Now

- `ethics.pdf` is document `1`.
- `history.pdf` is document `2`.
- PDF ingestion works.
- 582 pages and 257 chunks exist in the current local database.
- `ethics.pdf` has 118 pages and 100 chunks. Section labels exist, with no
  unlabeled pages or chunks.
- `history.pdf` has 464 pages and 157 chunks. It is structured but still
  unlabeled: all 464 pages and 157 chunks are `unlabeled / unlabeled`.
- Structured extraction is complete for both local documents: 257/257 chunks
  have valid latest model output.
- Normalized records are populated across the database: 257 chunk summaries,
  497 topics, 905 key terms, 406 examples, and 611 questions.
- `ethics.pdf` has 100 chunk summaries, 112 topics, 251 key terms, 74 examples,
  and 186 questions. Non-core ethics chunks have zero persisted key
  terms/questions; admin/support material is summary-only.
- `history.pdf` has 157 chunk summaries, 385 topics, 654 key terms, 332
  examples, and 425 questions. Because it is unlabeled, those key terms and
  questions currently appear under the `unlabeled` role.
- `ask` works with local Ollama retrieval context.
- `chat` works with the same retrieval and answer path.
- `ask` and `chat` can write local JSON traces with `--trace-dir`.
- Comparison-aware retrieval works for retrieval-only benchmark cases.
- Chat follow-up and continuation context appears to be present.

## Working Model

The chosen working model for now is `gemma-python`, with thinking disabled by
default. Current defaults are:

- `ETHNOS_OLLAMA_STRUCTURE_NUM_PREDICT=2048`
- `ETHNOS_OLLAMA_ANSWER_NUM_PREDICT=1536`
- `ETHNOS_OLLAMA_NUM_CTX=8192`
- `ETHNOS_OLLAMA_THINK=false`
- `ETHNOS_OLLAMA_NUM_THREAD` unset

The current MC-only benchmark default is `mc-bench --chars 300`, with
`ETHNOS_OLLAMA_NUM_CTX=8192` and `ETHNOS_OLLAMA_NUM_THREAD` unset. The value is
based on the measured `caspian` benchmark ladder in the performance guide.
Mixed `quiz-bench` still uses `--chars 900` for essay drafts and broader answer
context.

The structure prompt is intentionally compact. Schema `title` metadata is kept
because removing it caused Gemma to omit required example fields in smoke tests.

## Local Data Inventory

`data/` is intentionally ignored by git, so this runtime state must be copied or
rebuilt during migration:

- `data/ethnos.sqlite`: about 11 MiB, contains both processed documents.
- `data/incoming/ethics.pdf`: about 1.9 MiB, SHA prefix `eac21ab05849`.
- `data/incoming/history.pdf`: about 6.9 MiB, SHA prefix `81ad69f0b520`.

There are 27 extraction runs in the current database. Every chunk's latest
output is valid.

## Smoke Checks

These checks are safe to run inside Codex for baseline verification:

```bash
python -m compileall -q src tests
.venv/bin/python -m pytest -q
.venv/bin/ethnos documents
.venv/bin/ethnos db-info
.venv/bin/ethnos section-status 1
.venv/bin/ethnos structure-status 1
.venv/bin/ethnos quality-report 1
.venv/bin/ethnos section-status 2
.venv/bin/ethnos structure-status 2
.venv/bin/ethnos quality-report 2
.venv/bin/ethnos qa-bench 1 --benchmark benchmarks/ethics_qa.json --no-ask
git status --short
```

## Expensive Commands To Avoid Inside Codex

Do not run these during baseline stabilization unless explicitly requested:

```bash
.venv/bin/ethnos qa-bench 1 --benchmark benchmarks/ethics_qa.json --ask
.venv/bin/ethnos structure 1 --force
.venv/bin/ethnos structure 1 --retry-failed
.venv/bin/ethnos structure 1 --all-roles
```

Also avoid long Ollama benchmarks, multi-model comparisons, PDF re-extraction,
structured re-extraction, and product-feature experiments during baseline
stabilization.

## Local Database Recovery

`data/ethnos.sqlite` is ignored local runtime state. Deleting or replacing it
does not delete the source code, but it does remove the local processed
database. The source PDFs for the current baseline are
`data/incoming/ethics.pdf` and `data/incoming/history.pdf`.

To recover from a missing, corrupted, or intentionally replaced database,
recreate `ethics.pdf` from the source PDF:

```bash
.venv/bin/ethnos ingest-pdf data/incoming/ethics.pdf
.venv/bin/ethnos chunk 1
.venv/bin/ethnos label-sections 1 --preset ethics
.venv/bin/ethnos structure 1
```

The `structure` step is expensive because it calls Ollama. By default it
processes only core/unlabeled chunks and skips admin/support chunks. Use
`--all-roles` only when you intentionally want model outputs for every labeled
chunk. Do not run long structure passes inside Codex during baseline
stabilization unless explicitly requested.

`history.pdf` can be rebuilt the same way, but it still needs a section-label
preset or manual labeling before role-filtered retrieval is meaningful:

```bash
.venv/bin/ethnos ingest-pdf data/incoming/history.pdf
.venv/bin/ethnos chunk 2
.venv/bin/ethnos structure 2
```

To back up the current processed database manually, copy
`data/ethnos.sqlite` to another file under `data/` or to a location outside the
repo. Database backups should stay ignored local data and should not be
committed.

## Next Sensible Project Areas

- Label `history.pdf` pages/chunks or add a history section preset.
- Add a small troubleshooting guide for Ollama connection and model-loading failures.
- Clarify how traces should be inspected when an answer looks suspicious.
- Tighten tests around chat continuation behavior.
