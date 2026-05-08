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

## Next Sensible Project Areas

- Improve recovery notes for restoring or replacing the local SQLite database.
- Add a small troubleshooting guide for Ollama connection and model-loading failures.
- Clarify how traces should be inspected when an answer looks suspicious.
- Tighten tests around chat continuation behavior.
