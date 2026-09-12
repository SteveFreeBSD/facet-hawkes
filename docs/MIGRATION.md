# Migration Checklist

> **Scope: the local study engine.** This reproduces the PDF study, quiz and
> review side on another machine. It is not how the live Hawkes system is
> deployed -- that is [Runtime, models and
> deployment](RUNTIME_AND_DEPLOYMENT.md), and the current system runs on one
> machine that is already set up. Sections 4 to 6 below are `caspian`-era
> procedure for an AMD iGPU host and were last exercised there; the model
> names in them are the current defaults, but the acceleration figures are
> not from this host.

Git contains source, tests, prompts, fixtures, and documentation. The processed
database, PDFs, reports, and Ollama model store are separate local state.

## 1. Copy the tracked sibling repositories

Requirements: Python 3.12 or newer (matching `requires-python` in
`pyproject.toml`), `uv`, Git, SQLite with FTS5, and Ollama.

Facet Hawkes Assistant 0.46.0 requires Facet runtime commit
`af305628c77785229d7bc36dbfabf9205abc3bd8`. Keep both repositories under one
parent directory because `pyproject.toml` deliberately resolves the runtime at
`../facet-runtime`.

```bash
mkdir facet-hawkes-0.46.0
cd facet-hawkes-0.46.0
git clone https://github.com/SteveFreeBSD/facet-hawkes.git
git clone https://github.com/SteveFreeBSD/facet-runtime.git
# `main` is a frozen release baseline in both. The current system is here:
git -C facet-hawkes checkout feature/live-hawkes-next-slice
git -C facet-runtime checkout --detach af305628c77785229d7bc36dbfabf9205abc3bd8
cd facet-hawkes
uv sync --frozen --extra dev
uv run pytest -q
uv run ruff check .
```

The commit above is `deploy/facet-runtime.pin`, which is the only place it is
decided; `tests/test_runtime_pin.py` fails if this checklist drifts from it.

Facet is the solver, and `facet-remote` is a separate `uv tool` installation
rather than the working tree. Install it, or nothing can be solved:

```bash
cd ../facet-runtime
uv tool install --force --reinstall .
```

To run the Hawkes add-on as well as the study engine, register the native
companion — see [Runtime, models and
deployment](RUNTIME_AND_DEPLOYMENT.md#deploying-a-change).

Historical baseline figures are in
[the historical record](history/README.md).

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

Expected counts were recorded on `caspian` in
[the historical baseline](history/CURRENT_BASELINE.md); they describe that
corpus, not necessarily a new one.

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

The only required model name is `qwen3.5:9b`. Screenshot questions
additionally use `qwen3.5:4b` as the first of two different readers.

For a `caspian`-class AMD iGPU host, create:

```text
/etc/systemd/system/ollama.service.d/override.conf
```

Copy the verified drop-in from [the Caspian host
profile](history/CASPIAN_HOST.md#vulkan-and-ollama). That profile is historical
but is still the recorded service block and post-change checks for that class
of host.

Apply and verify:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
systemctl show ollama -p ActiveState -p SubState -p Environment -p LimitMEMLOCK
ollama --version
```

On another GPU architecture, verify the appropriate Ollama backend instead of
blindly copying `OLLAMA_IGPU_ENABLE`.

## 5. Obtain the models

The current models are upstream tags, not local aliases. Pull them:

```bash
ollama pull qwen3.5:9b
ollama pull qwen3.5:4b
```

Confirm what is present:

```bash
ollama list
ollama show qwen3.5:9b
```

> **Historical.** Earlier revisions of this checklist built a local alias from
> a Modelfile, and after the models changed the recipe survived as an
> instruction to *create* `qwen3.5:9b` from a different base — which would
> shadow the real tag with a small unrelated model. Do not do that. The alias
> recipe, and the `precalc-local` math alias, exist only on `caspian`: see
> [the historical baseline](history/CURRENT_BASELINE.md) and
> [Pre-calculus setup](PRECALCULUS.md).

Copying `/var/lib/ollama` between hosts requires preserving the Ollama service
account's ownership.

## 6. Verify model acceleration

```bash
ollama run qwen3.5:9b "Reply exactly: model ready"
ollama ps
```

On a working iGPU host, expect `100% GPU` and context `4096` — that was the
measured result on `caspian`. Then run an
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
command and pass criteria in [the historical performance
notes](history/PERFORMANCE_TUNING.md). No current acceptance figure exists for
this host; the benchmark needs re-running before one is quoted.
