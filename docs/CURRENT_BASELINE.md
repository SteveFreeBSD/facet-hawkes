# Current Baseline

This is the known-good local baseline for `ethnos`.

## What Works Now

- `ethics.pdf` is document `1`.
- PDF ingestion works.
- Chunks exist.
- Section labels exist, with no unlabeled pages or chunks in the current database.
- `ask` works with local Ollama retrieval context.
- `chat` works with the same retrieval and answer path.
- `ask` and `chat` can write local JSON traces with `--trace-dir`.
- Comparison-aware retrieval works for retrieval-only benchmark cases.
- Chat follow-up and continuation context appears to be present.

## Working Model

The chosen working model for now is `gemma-python`.

## Smoke Checks

These checks are safe to run inside Codex for baseline verification:

```bash
python -m compileall -q src tests
.venv/bin/uv run pytest -q
.venv/bin/uv run ethnos documents
.venv/bin/uv run ethnos db-info
.venv/bin/uv run ethnos section-status 1
.venv/bin/uv run ethnos qa-bench 1 --benchmark benchmarks/ethics_qa.json --no-ask
git status --short
```

## Expensive Commands To Avoid Inside Codex

Do not run these during baseline stabilization unless explicitly requested:

```bash
.venv/bin/uv run ethnos qa-bench 1 --benchmark benchmarks/ethics_qa.json --ask
.venv/bin/uv run ethnos structure 1 --force
.venv/bin/uv run ethnos structure 1 --retry-failed
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

The `structure` step is expensive because it calls Ollama. Do not run it inside
Codex during baseline stabilization unless explicitly requested.

To back up the current processed database manually, copy
`data/ethnos.sqlite` to another file under `data/` or to a location outside the
repo. Database backups should stay ignored local data and should not be
committed.

## Next Sensible Project Areas

- Add a small troubleshooting guide for Ollama connection and model-loading failures.
- Clarify how traces should be inspected when an answer looks suspicious.
- Tighten tests around chat continuation behavior.
