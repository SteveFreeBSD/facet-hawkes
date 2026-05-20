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
  498 topics, 906 key terms, 406 examples, and 611 questions.
- `ethics.pdf` has 100 chunk summaries, 113 topics, 252 key terms, 74 examples,
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

These checks are safe to run inside Codex for baseline verification:

```bash
python -m compileall -q src tests
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

## Expensive Commands To Avoid Inside Codex

Do not run these during baseline stabilization unless explicitly requested:

```bash
uv run ethnos qa-bench 1 --benchmark benchmarks/ethics_qa.json --ask
uv run ethnos structure 1 --force
uv run ethnos structure 1 --retry-failed
uv run ethnos structure 1 --all-roles
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
uv run ethnos ingest-pdf data/incoming/ethics.pdf
uv run ethnos chunk 1
uv run ethnos label-sections 1 --preset ethics
uv run ethnos structure 1
```

The `structure` step is expensive because it calls Ollama. By default it
processes only core/unlabeled chunks and skips admin/support chunks. Use
`--all-roles` only when you intentionally want model outputs for every labeled
chunk. Do not run long structure passes inside Codex during baseline
stabilization unless explicitly requested.

`history.pdf` can be rebuilt the same way, but it still needs a section-label
preset or manual labeling before role-filtered retrieval is meaningful:

```bash
uv run ethnos ingest-pdf data/incoming/history.pdf
uv run ethnos chunk 2
uv run ethnos structure 2
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
