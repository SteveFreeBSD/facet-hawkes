# ethnos

`ethnos` is a local-first PDF-to-knowledge pipeline for course material. It turns human-readable PDFs into structured, searchable records while preserving the raw inputs, source page metadata, chunk boundaries, prompts, and raw model outputs.

The project intentionally starts with simple foundations:

- `uv` for project and dependency management
- PyMuPDF for PDF text extraction
- Pydantic v2 for validation and JSON schema
- SQLite and FTS5 for local storage and search
- Ollama for local structured extraction

No cloud APIs are used.

## Setup

Install `uv`, then run:

```bash
uv sync --extra dev
```

## Basic Use

```bash
uv run ethnos ingest-pdf path/to/course.pdf
uv run ethnos documents
uv run ethnos chunk 1
uv run ethnos structure-status 1
uv run ethnos search "photosynthesis"
uv run ethnos export-markdown 1
```

For a small Ollama smoke test, limit `structure` to one chunk:

```bash
uv run ethnos structure 1 --limit 1 --debug-ollama
```

By default, `structure` processes chunks that have never been attempted. Use
`--retry-failed` to retry chunks whose latest model output failed, and use
`--force` only when you intentionally want to reprocess chunks that already
have a valid model output. Raw model outputs and extraction-run history are
preserved.

The default structured-output budget is `8192` tokens. Override it with:

```bash
uv run ethnos structure 1 --num-predict 12000
```

Markdown export can write to a file to avoid flooding the terminal:

```bash
uv run ethnos export-markdown 1 --output data/processed/ethics.md
```

The default database path is `data/ethnos.sqlite`. You can override it:

```bash
ETHNOS_DB_PATH=/path/to/ethnos.sqlite uv run ethnos db-info
```

## Ollama

The default model is `gemma-python` at `http://localhost:11434`.

```bash
uv run ethnos structure 1
```

Override defaults with:

```bash
ETHNOS_OLLAMA_MODEL=gemma-python
ETHNOS_OLLAMA_HOST=http://localhost:11434
ETHNOS_OLLAMA_TIMEOUT=300
ETHNOS_OLLAMA_NUM_PREDICT=8192
```
