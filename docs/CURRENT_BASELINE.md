# Current Baseline

This is the known-good local baseline for `ethnos`.

## What Works Now

- `ethics.pdf` is document `1`.
- PDF ingestion works.
- 118 pages and 100 chunks exist in the current local database.
- Section labels exist, with no unlabeled pages or chunks in the current database.
- Structured extraction is complete for the current local database: 100/100
  chunks have a valid latest model output.
- Normalized records are populated: 100 chunk summaries, 112 topics, 251 key
  terms, 74 examples, and 186 questions.
- Non-core chunks have zero persisted key terms/questions; admin/support
  material is summary-only.
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

The local Ollama service has `OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_MLOCK=1`
enabled, with `LimitMEMLOCK=infinity`. A one-chunk smoke comparison showed a
modest flash-attention improvement, with normal run-to-run variance.
Per-request `use_mlock` was rejected by this Ollama build, and forcing
`num_thread=16` was slower on the Ryzen 7 PRO 5850U CPU path.

The structure prompt is intentionally compact. Schema `title` metadata is kept
because removing it caused Gemma to omit required example fields in smoke tests.

## Smoke Checks

These checks are safe to run inside Codex for baseline verification:

```bash
python -m compileall -q src tests
.venv/bin/uv run pytest -q
.venv/bin/uv run ethnos documents
.venv/bin/uv run ethnos db-info
.venv/bin/uv run ethnos section-status 1
.venv/bin/uv run ethnos structure-status 1
.venv/bin/uv run ethnos quality-report 1
.venv/bin/uv run ethnos qa-bench 1 --benchmark benchmarks/ethics_qa.json --no-ask
git status --short
```

## Expensive Commands To Avoid Inside Codex

Do not run these during baseline stabilization unless explicitly requested:

```bash
.venv/bin/uv run ethnos qa-bench 1 --benchmark benchmarks/ethics_qa.json --ask
.venv/bin/uv run ethnos structure 1 --force
.venv/bin/uv run ethnos structure 1 --retry-failed
.venv/bin/uv run ethnos structure 1 --all-roles
```

Also avoid long Ollama benchmarks, multi-model comparisons, PDF re-extraction,
structured re-extraction, and product-feature experiments during baseline
stabilization.

## Local Database Recovery

`data/ethnos.sqlite` is ignored local runtime state. Deleting or replacing it
does not delete the source code, but it does remove the local processed
database. The source PDF for the current baseline is
`data/incoming/ethics.pdf`.

To recover from a missing, corrupted, or intentionally replaced database,
recreate it from the source PDF:

```bash
.venv/bin/uv run ethnos ingest-pdf data/incoming/ethics.pdf
.venv/bin/uv run ethnos chunk 1
.venv/bin/uv run ethnos label-sections 1
.venv/bin/uv run ethnos structure 1
```

The `structure` step is expensive because it calls Ollama. By default it
processes only core/unlabeled chunks and skips admin/support chunks. Use
`--all-roles` only when you intentionally want model outputs for every labeled
chunk. Do not run long structure passes inside Codex during baseline
stabilization unless explicitly requested.

To back up the current processed database manually, copy
`data/ethnos.sqlite` to another file under `data/` or to a location outside the
repo. Database backups should stay ignored local data and should not be
committed.

## Next Sensible Project Areas

- Add a small troubleshooting guide for Ollama connection and model-loading failures.
- Clarify how traces should be inspected when an answer looks suspicious.
- Tighten tests around chat continuation behavior.
