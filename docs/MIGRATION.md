# Migration Checklist

Use this checklist to reproduce Ethnos on another machine. Git contains source,
tests, prompts, fixtures, and documentation. The processed database, PDFs,
reports, and Ollama model store are separate local state.

## 1. Copy the tracked sibling repositories

Requirements: Python 3.11+, `uv`, Git, SQLite with FTS5, and Ollama.

Facet Hawkes Assistant 0.46.0 requires Facet runtime commit
`f2e09071415907cbbe1b4b905af9af6473098e8b`. Keep both repositories under one
parent directory because `pyproject.toml` deliberately resolves the runtime at
`../facet-runtime`.

```bash
mkdir facet-hawkes-0.46.0
cd facet-hawkes-0.46.0
git clone https://github.com/SteveFreeBSD/facet-hawkes.git
git clone https://github.com/SteveFreeBSD/facet-runtime.git
git -C facet-runtime checkout --detach f2e09071415907cbbe1b4b905af9af6473098e8b
cd facet-hawkes
uv sync --frozen --extra dev
uv run pytest -q
uv run ruff check .
```

Read [CURRENT_BASELINE.md](CURRENT_BASELINE.md) before copying runtime state.
Machine-specific differences belong under [hosts/](hosts/README.md).

## 2. Copy or rebuild local data

To preserve processed state, copy these ignored files with the application
stopped:

```text
data/ethnos.sqlite
data/incoming/ethics.pdf
data/incoming/history.pdf
```

Optional local evidence:

```text
data/runs/
data/processed/
```

Do not copy `.venv`, Python caches, or build artifacts. Recreate dependencies
from `uv.lock`.

Verify copied data:

```bash
uv run ethnos documents
uv run ethnos db-info
uv run ethnos structure-status 1
uv run ethnos structure-status 2
```

Expected counts are recorded in [CURRENT_BASELINE.md](CURRENT_BASELINE.md).

## 3. Configure application overrides only if needed

Built-in defaults already select `qwen3.5:9b`, context `4096`, and
`think=false`. `.env.example` is a template, not an automatically loaded file.

```bash
cp .env.example .env
uv run --env-file .env ethnos documents
```

Use the `--env-file` form consistently, or export the variables in the shell or
service that launches Ethnos.

## 4. Configure Ollama

The only required model name is `qwen3.5:9b`. Qwen is optional and should not
be copied to a new Ethnos host unless a separate workflow needs it.

For a Caspian-class AMD iGPU host, create:

```text
/etc/systemd/system/ollama.service.d/override.conf
```

Copy the verified drop-in from
[hosts/caspian.md](hosts/caspian.md#vulkan-and-ollama). That host profile is the
single source of truth for the exact service block and post-change checks.

Apply and verify:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
systemctl show ollama -p ActiveState -p SubState -p Environment -p LimitMEMLOCK
ollama --version
```

On another GPU architecture, verify the appropriate Ollama backend instead of
blindly copying `OLLAMA_IGPU_ENABLE`.

## 5. Recreate the Gemma alias

First check whether it already exists:

```bash
ollama show qwen3.5:9b
```

If not, save the following as a Modelfile and create the alias:

```text
FROM gemma4:e2b

SYSTEM """
You are a concise Python scripting helper for a beginner college class.
When asked for code, give the code first.
Keep explanations short.
Do not create long tutorials unless asked.
Do not add setup sections unless needed.
Prefer simple, readable Python.
"""

PARAMETER num_ctx 4096
PARAMETER num_predict 500
PARAMETER temperature 0.2
PARAMETER top_k 64
PARAMETER top_p 0.95
```

```bash
ollama create qwen3.5:9b -f /path/to/Modelfile
```

For exact reproduction across an upstream tag change, export the source host's
generated Modelfile with `ollama show qwen3.5:9b --modelfile` and preserve the
referenced Ollama store. Copying `/var/lib/ollama` requires preserving the
Ollama service account's ownership.

## 6. Verify model acceleration

```bash
ollama run qwen3.5:9b "Reply exactly: model ready"
ollama ps
```

On `caspian`, expected output is `100% GPU` and context `4096`. Then run an
Ethnos smoke without mutating the database:

```bash
uv run ethnos ask 1 "What is virtue ethics?" --limit 2 --debug-ollama
```

If the model is missing, CPU-only, empty, truncated, or unstable, stop and use
[OLLAMA_TROUBLESHOOTING.md](OLLAMA_TROUBLESHOOTING.md).

## 7. Rebuild instead of copying the database

If no processed database is available:

```bash
uv run ethnos ingest-pdf data/incoming/ethics.pdf
uv run ethnos chunk 1
uv run ethnos label-sections 1 --preset ethics
uv run ethnos structure 1 --limit 1 --debug-ollama
uv run ethnos structure 1 --all-roles

uv run ethnos ingest-pdf data/incoming/history.pdf
uv run ethnos chunk 2
uv run ethnos label-sections 2 --preset history
uv run ethnos structure 2 --limit 1 --debug-ollama
uv run ethnos structure 2 --all-roles
```

The one-chunk smokes are intentional. Full `structure --all-roles` runs are
expensive. If labels are applied after structure output already exists, run:

```bash
uv run ethnos refresh-records DOCUMENT_ID
```

## 8. Final acceptance

```bash
uv run pytest -q
uv run ruff check .
uv run ethnos documents
uv run ethnos db-info
uv run ethnos section-status 1
uv run ethnos structure-status 1
uv run ethnos section-status 2
uv run ethnos structure-status 2
uv run ethnos qa-bench 1 --benchmark benchmarks/ethics_qa.json --no-ask
ollama ps
```

Run the full model acceptance benchmark only after these checks pass. Use the
command and pass criteria in [PERFORMANCE_TUNING.md](PERFORMANCE_TUNING.md).
