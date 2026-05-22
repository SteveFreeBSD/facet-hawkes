# Migration Checklist

Use this checklist when moving `ethnos` and its local Ollama setup to another
machine. Git tracks source and documentation only. Runtime data, PDFs, local
benchmark outputs, and Ollama model stores live outside the tracked tree.

## Source Of Truth

- GitHub repo: `git@github.com:SteveFreeBSD/ethnos.git`
- CTO review packet: [`CTO_REVIEW.md`](CTO_REVIEW.md)
- App/data baseline: [`CURRENT_BASELINE.md`](CURRENT_BASELINE.md)
- Performance defaults: [`PERFORMANCE_TUNING.md`](PERFORMANCE_TUNING.md)
- Ollama troubleshooting: [`OLLAMA_TROUBLESHOOTING.md`](OLLAMA_TROUBLESHOOTING.md)
- Host profiles: [`hosts/`](hosts/)
- Environment template: [`.env.example`](../.env.example)

Update the docs in the same commit as setup changes so migration instructions
do not drift from the real machines.

## What To Move

- Repo source: `uv.lock`, `pyproject.toml`, `src/`, `tests/`, `benchmarks/`,
  `prompts/`, `.github/`, and `docs/`.
- Ignored runtime data if preserving processed state:
  `data/ethnos.sqlite`, `data/incoming/ethics.pdf`, and
  `data/incoming/history.pdf`.
- Optional ignored outputs under `data/runs/` and `data/processed/` if prior
  benchmark reports, traces, or exports matter.
- Ollama model availability: `gemma-python` is required.
- Ollama service override at
  `/etc/systemd/system/ollama.service.d/override.conf`.

Do not copy `.venv`, caches, or extra Ollama models unless there is a specific
reason. Rebuild dependencies from `uv.lock`.

## Set Up A New Host

1. Install Python 3.11 or newer, `uv`, SQLite with FTS5 support, git, and
   Ollama.
2. Clone the repo:

```bash
git clone git@github.com:SteveFreeBSD/ethnos.git
cd ethnos
uv sync --extra dev
```

3. Copy `.env.example` to `.env` only when local overrides are needed:

```bash
cp .env.example .env
```

4. Copy ignored data if preserving the current processed database:

```bash
mkdir -p data/incoming
cp /source/ethnos/data/ethnos.sqlite data/ethnos.sqlite
cp /source/ethnos/data/incoming/ethics.pdf data/incoming/ethics.pdf
cp /source/ethnos/data/incoming/history.pdf data/incoming/history.pdf
```

5. Install or recreate only the required Ollama model name:

```bash
ollama list
ollama show gemma-python
```

If `gemma-python` is missing, recreate it from the documented Modelfile below
or copy the existing Ollama store with ownership preserved.

## Ollama Service Settings

Common drop-in:

```ini
[Service]
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_MLOCK=1"
LimitMEMLOCK=infinity
```

For hosts doing repeated local runs, also add:

```ini
Environment="OLLAMA_KEEP_ALIVE=30m"
```

Apply and verify:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
systemctl show ollama -p Environment -p LimitMEMLOCK -p ActiveState -p SubState
ollama --version
ollama list
```

Record host-specific differences in a file under [`hosts/`](hosts/).

## Model Alias

The app default is `gemma-python`. The current alias was created from:

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

Runtime requests from `ethnos` override context and output budgets for
structure, ask, chat, and benchmark commands. The important migration invariant
is that the `gemma-python` model name exists and behaves like the tested Gemma
alias.

## Verify The Migration

Run cheap checks first:

```bash
uv run ruff check .
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
cheap checks pass.

## Rebuild Instead Of Copying Data

If the database is not copied, rebuild from source PDFs:

```bash
uv run ethnos ingest-pdf data/incoming/ethics.pdf
uv run ethnos chunk 1
uv run ethnos label-sections 1 --preset ethics
uv run ethnos structure 1 --all-roles

uv run ethnos ingest-pdf data/incoming/history.pdf
uv run ethnos chunk 2
uv run ethnos label-sections 2 --preset history
uv run ethnos structure 2 --all-roles
```

The baseline keeps model outputs and summaries for every chunk, which is why
the exact rebuild uses `--all-roles`. If you apply labels after a document was
already structured, run `uv run ethnos refresh-records <document_id>` so
normalized key terms/questions are rebuilt from the current roles.

## Final Sync Check

Before calling a migrated host ready:

```bash
git status --short --branch
git remote -v
git push --dry-run origin main
ollama list
systemctl show ollama -p Environment -p LimitMEMLOCK -p ActiveState -p SubState
```
