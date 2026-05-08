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
uv run ethnos section-status 1
uv run ethnos search "photosynthesis"
uv run ethnos inspect-chunk 1 80 --records
uv run ethnos records 1 --type key_terms --role core --limit 10
uv run ethnos quality-report 1
uv run ethnos context 1 "methodological ethical naturalism" --limit 3
uv run ethnos ask 1 "What is methodological ethical naturalism?"
uv run ethnos chat 1
uv run ethnos qa-bench 1 --benchmark benchmarks/ethics_qa.json --no-ask
uv run ethnos export-markdown 1
uv run ethnos export-study 1 --output data/processed/study-guide.md
```

For a small Ollama smoke test, limit `structure` to one chunk:

```bash
uv run ethnos structure 1 --limit 1 --debug-ollama
```

By default, `structure` processes core/unlabeled chunks that have never been
attempted, skipping admin/support chunks to avoid spending Ollama time on
non-study material. Use `--all-roles` when you intentionally want structured
outputs for every labeled chunk. Use `--retry-failed` to retry chunks whose
latest model output failed, and use `--force` only when you intentionally want
to reprocess chunks that already have a valid model output. Raw model outputs
and extraction-run history are preserved.

The default structured-output budget is `2048` tokens. Override it with:

```bash
uv run ethnos structure 1 --num-predict 3072
```

Markdown export can write to a file to avoid flooding the terminal:

```bash
uv run ethnos export-markdown 1 --output data/processed/ethics.md
```

## Inspecting Assimilated Knowledge

`section_label` names the kind of document section, such as `chapter_content`,
`chapter_references`, `front_matter`, or `accessibility`. `content_role` is a
broader bucket for filtering: `core`, `support`, `admin`, `artifact`, or
`unknown`.

Inspect one chunk:

```bash
uv run ethnos inspect-chunk 1 80
uv run ethnos inspect-chunk 1 80 --full-text
uv run ethnos inspect-chunk 1 80 --records
```

Filter full-text search by section metadata:

```bash
uv run ethnos search "evolutionary ethics" --role core
uv run ethnos search "references" --section chapter_references
```

List normalized structured records:

```bash
uv run ethnos records 1 --type key_terms --role core --limit 10
uv run ethnos records 1 --type questions --section chapter_content --limit 10
uv run ethnos records 1 --chunk-id 80
```

Summarize the shape and quality of the assimilated data without calling Ollama:

```bash
uv run ethnos section-status 1
uv run ethnos structure-status 1
uv run ethnos quality-report 1
```

Show retrieval-ready context for a query without asking a model:

```bash
uv run ethnos context 1 "methodological ethical naturalism" --limit 3
uv run ethnos context 1 "license" --role admin --chars 500
```

Ask a local model a grounded question using retrieved PDF context:

```bash
uv run ethnos ask 1 "What is methodological ethical naturalism?"
uv run ethnos ask 1 "What are the main ideas in evolutionary ethics?" --limit 4
uv run ethnos ask 1 "Tell me about the accessibility checklist" --role all --limit 3
uv run ethnos ask 1 "What is virtue ethics?" --trace-dir data/runs
```

`ask` uses local Ollama only. It retrieves FTS5 context first, defaults to
`--role core`, sends only the selected context and question to the model, and
does not mutate the database. Use `--role all` to search across all labeled
roles.

The current default working model is `gemma-python`, with temperature `0`, an
answer budget from `ETHNOS_OLLAMA_ANSWER_NUM_PREDICT` (`1536` by default), and
context from `ETHNOS_OLLAMA_NUM_CTX` (`8192` by default). Override the model or
context window per call:

```bash
uv run ethnos ask 1 "What is virtue ethics?" --model gemma-python
uv run ethnos ask 1 "What is virtue ethics?" --num-ctx 32768
```

Start a simple local terminal loop with the same retrieval and answer path:

```bash
uv run ethnos chat 1
uv run ethnos chat 1 --role core --limit 4 --trace-dir data/runs
```

In chat mode, type a question and press Enter. Type `quit`, `exit`, or `:q` to
leave. Empty input is ignored.

Use `--trace-dir` with `ask` or `chat` when you want inspectable local JSON
traces of answered questions. Traces include the question, derived retrieval
queries, selected chunks, citations, model name, answer text, and timings. They
are not written by default. Keep them under `data/runs/` so they stay local and
ignored by git.

Run the local retrieval-only benchmark without calling Ollama:

```bash
uv run ethnos qa-bench 1 --benchmark benchmarks/ethics_qa.json --no-ask
```

Refresh normalized records from existing valid model outputs after changing
storage policy, without calling Ollama:

```bash
uv run ethnos refresh-records 1
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
ETHNOS_OLLAMA_STRUCTURE_NUM_PREDICT=2048
ETHNOS_OLLAMA_ANSWER_NUM_PREDICT=1536
ETHNOS_OLLAMA_NUM_CTX=8192
ETHNOS_OLLAMA_THINK=false
```

By default ethnos sends `think=false` to Ollama because local Gemma models can
spend the whole output budget on hidden thinking tokens. `--debug-ollama`
reports `message_thinking_length` so this is visible during smoke checks.

On the current CPU-only baseline machine, `OLLAMA_FLASH_ATTENTION=1` is enabled
as an Ollama service override and gave a modest one-chunk speed improvement.
Per-request `use_mlock` was rejected by the installed Ollama build, and forcing
16 threads was slower than the default/8-thread CPU path. Treat service and
thread tuning as benchmarked local configuration, not portable project
defaults.

The current local `ethics.pdf` database baseline has 100/100 chunks with valid
latest structured output, 100 chunk summaries, 251 key terms, 187 questions, and
zero non-core key terms/questions.
