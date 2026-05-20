# Migration Checklist

Use this checklist when moving `ethnos` and the tuned local Ollama setup to a
different machine. The app is local-first, so git alone is not enough:
processed databases, PDFs, custom Ollama model names, and service overrides all
live outside the tracked source tree.

## What To Move

- The repo source, including `uv.lock`, `prompts/`, `src/`, `tests/`,
  `benchmarks/`, and `docs/`.
- Ignored runtime data if you want to keep the current processed state:
  `data/ethnos.sqlite`, `data/incoming/ethics.pdf`, and
  `data/incoming/history.pdf`.
- Optional ignored run artifacts under `data/runs/` and `data/processed/` if
  you want prior benchmark traces, exported reports, or study guides.
- Ollama model availability and aliases: `gemma-python` is required for the
  current baseline.
- The Ollama systemd drop-in at
  `/etc/systemd/system/ollama.service.d/override.conf`.

## Current Local Snapshot

Observed local state:

| Area | Value |
|---|---|
| OS/kernel | CachyOS, CachyOS kernel 7.0.9 |
| CPU | AMD Ryzen Embedded V1756B, 4 cores / 8 threads |
| GPU for Ollama | Integrated Radeon Vega present; Ollama currently uses CPU |
| RAM/swap | 62 GiB RAM, 62 GiB zram, essentially no swap used at idle |
| Ollama | 0.24.0 |
| Ollama service | active, systemd service owned by `ollama` |
| Ollama override | `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_MLOCK=1`, `OLLAMA_KEEP_ALIVE=30m`, `LimitMEMLOCK=infinity` |
| Repo database | `data/ethnos.sqlite`, about 11 MiB |
| Default app model | `gemma-python` |

The app defaults are:

```bash
ETHNOS_DB_PATH=data/ethnos.sqlite
ETHNOS_OLLAMA_HOST=http://localhost:11434
ETHNOS_OLLAMA_MODEL=gemma-python
ETHNOS_OLLAMA_TIMEOUT=300
ETHNOS_OLLAMA_STRUCTURE_NUM_PREDICT=2048
ETHNOS_OLLAMA_ANSWER_NUM_PREDICT=1536
ETHNOS_OLLAMA_NUM_CTX=8192
ETHNOS_OLLAMA_THINK=false
ETHNOS_OLLAMA_NUM_THREAD=
```

## Set Up The New Machine

1. Install Python 3.11 or newer, `uv`, SQLite with FTS5 support, and Ollama.
2. Clone or copy the repo.
3. From the repo root, run `uv sync --extra dev`.
4. Copy ignored local data into place if preserving the processed state:

```bash
mkdir -p data/incoming
cp /source/ethnos/data/ethnos.sqlite data/ethnos.sqlite
cp /source/ethnos/data/incoming/ethics.pdf data/incoming/ethics.pdf
cp /source/ethnos/data/incoming/history.pdf data/incoming/history.pdf
```

5. If `uv` is not available yet but the repo already has a working `.venv`, use
   `.venv/bin/ethnos` for verification. For a clean migration, prefer rebuilding
   the virtualenv from `uv.lock` instead of copying `.venv`.

## Recreate Ollama Service Settings

Create this drop-in on the new system:

```ini
[Service]
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_MLOCK=1"
Environment="OLLAMA_KEEP_ALIVE=30m"
LimitMEMLOCK=infinity
```

Apply and verify:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
systemctl show ollama -p Environment -p LimitMEMLOCK -p ActiveState -p SubState
ollama --version
```

## Recreate Ollama Models

The app's default model name is `gemma-python`. On this machine it is a local
alias over the same base blob as `gemma4:e2b`, with these important settings:

```text
FROM gemma4:e2b
TEMPLATE {{ .Prompt }}
SYSTEM "You are a concise Python scripting helper for a beginner college class.
When asked for code, give the code first.
Keep explanations short.
Do not create long tutorials unless asked.
Do not add setup sections unless needed.
Prefer simple, readable Python."
PARAMETER num_ctx 4096
PARAMETER num_predict 500
PARAMETER temperature 0.2
PARAMETER top_k 64
PARAMETER top_p 0.95
```

After pulling or copying the base model, recreate the alias with a temporary
Modelfile:

```bash
ollama create gemma-python -f Modelfile.gemma-python
ollama list
```

For an exact model-store migration instead, stop Ollama and copy
`/var/lib/ollama` with ownership/permissions preserved, then start Ollama on the
new host. That preserves blobs and manifests, but recreating aliases from
Modelfiles is easier to audit.

The repo's runtime requests override the model defaults for structured
extraction and answering, so the critical migration detail is that the model
names exist and support the Gemma chat/parser behavior expected by Ollama.

## Verify The Migration

Run these low-cost checks before any long Ollama job:

```bash
uv run pytest -q
uv run ethnos documents
uv run ethnos db-info
uv run ethnos structure-status 1
uv run ethnos structure-status 2
uv run ethnos quality-report 1
uv run ethnos quality-report 2
uv run ethnos qa-bench 1 --benchmark benchmarks/ethics_qa.json --no-ask
```

Then smoke-test Ollama without mutating the database:

```bash
uv run ethnos ask 1 "What is virtue ethics?" --limit 2 --debug-ollama
```

Only run full `structure`, `quiz-bench`, or multi-model comparisons after the
cheap checks pass. Full structure extraction is intentionally expensive on the
current CPU-only baseline.

## Rebuild Instead Of Copying Data

If the database is not copied, rebuild from source PDFs:

```bash
uv run ethnos ingest-pdf data/incoming/ethics.pdf
uv run ethnos chunk 1
uv run ethnos label-sections 1 --preset ethics
uv run ethnos structure 1

uv run ethnos ingest-pdf data/incoming/history.pdf
uv run ethnos chunk 2
uv run ethnos structure 2
```

`history.pdf` currently has no labels in the local database. After migration,
add a section preset or manual labels before treating role-filtered retrieval or
non-core quality reports as final.
