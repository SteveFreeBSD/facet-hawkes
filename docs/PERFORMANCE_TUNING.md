# Performance Tuning

This guide is the shared tuning playbook for `ethnos`. Hardware-specific facts
belong in [`docs/hosts/`](hosts/README.md); project defaults belong here only
when they are safe across the current hosts.

## Quick Defaults

- Use `gemma-python` as the working model.
- Keep `ETHNOS_OLLAMA_NUM_CTX=8192`.
- Keep `ETHNOS_OLLAMA_NUM_THREAD` unset for normal use.
- Keep `ETHNOS_OLLAMA_THINK=false`.
- Use `mc-bench --chars 300` for MC-only timing and comparison runs.
- Use `quiz-bench --chars 900` for mixed quizzes so essay drafts have more
  source context.
- Keep the Ollama service override small: flash attention, mlock, and memlock
  infinity. Add keep-alive on hosts where repeated local runs benefit from it.

These values reflect the measured `caspian` benchmark and still fit the faster
local `erosion` host. Re-test before changing defaults globally.

## Application Environment

Copy [`.env.example`](../.env.example) to `.env` only when local overrides are
needed. The app already has these defaults in code:

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

`ETHNOS_OLLAMA_NUM_THREAD` is intentionally blank. Ollama's default scheduler
was faster than fixed `4` or `6` thread settings in the measured MC benchmark
on `caspian`.

## Ollama Service Override

The common systemd drop-in path is:

```text
/etc/systemd/system/ollama.service.d/override.conf
```

Recommended baseline:

```ini
[Service]
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_MLOCK=1"
LimitMEMLOCK=infinity
```

For a workstation or benchmark host where repeated runs happen close together,
also add:

```ini
Environment="OLLAMA_KEEP_ALIVE=30m"
```

Apply and inspect:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
systemctl show ollama -p Environment -p LimitMEMLOCK -p ActiveState -p SubState
ollama --version
ollama list
```

Do not add per-request `use_mlock`; the installed Ollama build rejected that
option during earlier testing.

## Model Policy

The repo's default model name is `gemma-python`. For clean migrations and
repeatable benchmark comparisons, install only the model names the host needs.

`caspian` is intentionally lean and currently has only:

```text
gemma-python:latest
```

`erosion` has extra experimental local models, but they are not required for the
repo baseline and should not be treated as dependencies.

## Benchmark Protocol

Use one fixed quiz, change one variable, and save each report under
`data/runs/` so it stays out of git.

Create a fixed MC quiz:

```bash
uv run ethnos generate-quiz 1 \
  --source terms \
  --difficulty medium \
  --limit 20 \
  --seed 42 \
  --output data/runs/perf-quiz-medium-20.json
```

Run the current MC baseline:

```bash
uv run ethnos mc-bench 1 \
  --quiz data/runs/perf-quiz-medium-20.json \
  --num-ctx 8192 \
  --output data/runs/perf-baseline-mc.json
```

Run mixed quiz benchmarks separately:

```bash
uv run ethnos quiz-bench 1 \
  --quiz data/runs/perf-quiz-medium-20.json \
  --output data/runs/perf-baseline-mixed.json
```

Compare MC-only reports:

```bash
uv run ethnos mc-compare \
  data/runs/perf-baseline-mc.json \
  data/runs/perf-candidate-mc.json \
  --output data/runs/perf-compare-mc.json
```

Watch elapsed seconds, average answer seconds, accuracy, no-context count,
invalid-response count, selected chunks, retrieval queries, and whether the
model was already resident in `ollama ps`.

## Current MC Benchmark Result

The known MC tuning result was measured on
[`caspian`](hosts/caspian.md) with `gemma-python`,
`ETHNOS_OLLAMA_NUM_CTX=8192`, `ETHNOS_OLLAMA_NUM_THREAD` unset, and a fixed
20-question `perf-quiz-medium-20.json` quiz.

| Run | Context Text | Elapsed | Avg Answer | Accuracy | Notes |
|---|---:|---:|---:|---:|---|
| baseline rerun | 900 chars | 15m 20s | 46.01s | 90% | Original context size |
| shorter context | 600 chars | 12m 39s | 37.95s | 90% | Same accuracy |
| shorter context | 450 chars | 11m 49s | 35.42s | 90% | Same answers as 600 |
| current default | 300 chars | 10m 30s | 31.51s | 90% | Fastest safe MC setting tested |
| too short | 225 chars | 10m 10s | 30.48s | 85% | Accuracy cliff |
| performance profile, ctx4096 | 900 chars | 16m 21s | 49.05s | 90% | Slower |
| thread 4, ctx4096 | 900 chars | 16m 01s | 48.05s | 90% | Slower |
| thread 6, ctx4096 | 900 chars | 16m 09s | 48.47s | 90% | Slower |

Conclusion: keep `mc-bench --chars 300`, keep `num_ctx=8192`, and leave
`ETHNOS_OLLAMA_NUM_THREAD` unset. Do not use 225 chars as a default.

## SQLite Settings

`ethnos.db.connect()` applies:

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -32000;
PRAGMA temp_store = MEMORY;
PRAGMA mmap_size = 134217728;
```

For the current small database, SQLite is not the bottleneck. Revisit cache and
memory-map settings only when databases grow into hundreds of MiB or profiling
shows SQLite time dominating Ollama time.

## What Not To Tune Blindly

- Ollama thread count: use `ETHNOS_OLLAMA_NUM_THREAD` only for controlled A/B
  tests.
- Kernel VM knobs: avoid swappiness, dirty-ratio, transparent huge page, and
  scheduler changes unless monitoring points there.
- SQLite durability: keep WAL and `synchronous=NORMAL`; avoid
  `synchronous=OFF` for normal use.
- Larger context windows: raise `num_ctx` only when retrieval traces prove
  needed context is being truncated.
- Extra models: do not install them on the migration host unless a benchmark or
  workflow explicitly requires them.

## Host Profiles

- [`erosion`](hosts/erosion.md): local development host, Ryzen 7 PRO 5850U,
  Zen kernel, multiple local Ollama models.
- [`caspian`](hosts/caspian.md): migrated host, Ryzen Embedded V1756B,
  CachyOS, only `gemma-python`, measured MC tuning source.
