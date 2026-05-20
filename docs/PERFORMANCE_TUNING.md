# Performance Tuning

This guide captures local performance tuning for `ethnos` on the current
CPU-only development machine. Treat it as a measurement-driven playbook: apply
one change at a time, record the result, and keep reversible system changes out
of project defaults unless they prove stable. For machine-to-machine setup, use
the companion migration checklist in [`MIGRATION.md`](MIGRATION.md).

## Quick Recommendations

1. Run long Ollama benchmarks through CachyOS `game-performance` or switch
   `powerprofilesctl` to `performance` for the duration of the run.
2. Keep `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_MLOCK=1`,
   `OLLAMA_KEEP_ALIVE=30m`, and `LimitMEMLOCK=infinity`; they are already part
   of the local baseline.
3. Keep `ETHNOS_OLLAMA_NUM_CTX=8192` for the current `gemma-python` MC path.
   Local benchmarks found lower context and thread overrides slower.
4. Use the MC-only `mc-bench` default `--chars 300`. It was the fastest tested
   context size that preserved accuracy; `225` crossed the accuracy cliff.
5. Leave `ETHNOS_OLLAMA_NUM_THREAD` unset unless a fresh A/B benchmark proves a
   thread count repeatedly wins.
6. Leave SQLite and swap tuning alone until monitoring shows real pressure.

## Current Host Snapshot

This snapshot was observed on the local development machine and should be
rechecked after OS, kernel, Ollama, or hardware changes.

| Component | Observed Value |
|---|---|
| OS/kernel | CachyOS, CachyOS kernel 7.0.9 |
| CPU | AMD Ryzen Embedded V1756B, 4 cores / 8 threads |
| RAM | 62 GiB total, roughly 48 GiB available when idle |
| Storage | WD_BLACK SN850P NVMe SSD on Btrfs |
| GPU for Ollama | Integrated Radeon Vega is present; Ollama currently runs CPU-only |
| Ollama | 0.24.0 |
| Models | `gemma-python` 7.2 GB |
| CPU governor/profile | `schedutil`, CachyOS `balanced` profile |
| Swap | 62 GiB zram, essentially unused at idle |
| Database | `data/ethnos.sqlite`, about 11 MiB |

Useful inspection commands:

```bash
lscpu
free -h
swapon --show
cat /proc/sys/vm/swappiness
cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor | sort | uniq -c
powerprofilesctl get
ollama --version
ollama ps
ollama list
systemctl status ollama
```

## Ollama Service Settings

The current service override lives at:

```text
/etc/systemd/system/ollama.service.d/override.conf
```

Current local override:

```ini
[Service]
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_MLOCK=1"
Environment="OLLAMA_KEEP_ALIVE=30m"
LimitMEMLOCK=infinity
```

Apply changes:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
ollama ps
```

`OLLAMA_KEEP_ALIVE=30m` avoids paying cold-start model load cost between nearby
runs. It does not improve token generation speed once the model is already
loaded. Use `-1` only for dedicated long inference sessions where keeping the
model resident indefinitely is intentional.

Do not add per-request `use_mlock`; this installed Ollama build rejected that
option in prior testing.

## CPU Governor

CPU-only Ollama is compute-bound. The current CachyOS host uses the `schedutil`
governor under the `balanced` profile. Boost is enabled, but sustained
inference should be benchmarked under the performance profile.

Run one command under CachyOS performance mode:

```bash
game-performance uv run ethnos quiz-bench 1 \
  --quiz data/runs/perf-quiz-medium-20.json \
  --output data/runs/perf-cachyos-performance.json
```

Or switch manually for a longer session:

```bash
powerprofilesctl set performance
```

Revert when the run is done:

```bash
powerprofilesctl set balanced
```

Verify:

```bash
powerprofilesctl get
cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor | sort | uniq -c
```

The lower-level `cpupower` commands are still useful when diagnosing governor
behavior directly:

Enable performance mode:

```bash
sudo cpupower frequency-set -g performance
```

Revert when the run is done:

```bash
sudo cpupower frequency-set -g schedutil
```

Verify:

```bash
cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor | sort | uniq -c
```

If `cpupower` is missing on this Arch/CachyOS host, install the package that
provides it before using these commands:

```bash
sudo pacman -S cpupower
```

Suggested helper script, kept local and not required by the app:

```bash
#!/usr/bin/env bash
set -euo pipefail

case "${1:-}" in
  on)
    cpupower frequency-set -g performance
    ;;
  off)
    cpupower frequency-set -g schedutil
    ;;
  *)
    echo "Usage: $0 on|off" >&2
    exit 1
    ;;
esac
```

Expected effect: often meaningful for CPU-only inference, but thermal limits and
power policy matter. Benchmark before calling it a win.

## Application Defaults

Current `ethnos` Ollama defaults:

```bash
ETHNOS_OLLAMA_MODEL=gemma-python
ETHNOS_OLLAMA_HOST=http://localhost:11434
ETHNOS_OLLAMA_TIMEOUT=300
ETHNOS_OLLAMA_STRUCTURE_NUM_PREDICT=2048
ETHNOS_OLLAMA_ANSWER_NUM_PREDICT=1536
ETHNOS_OLLAMA_NUM_CTX=8192
ETHNOS_OLLAMA_THINK=false
# Optional benchmark knob. Leave unset for normal use.
ETHNOS_OLLAMA_NUM_THREAD=
```

`think=false` is intentional. Local Gemma models can spend the whole output
budget on hidden thinking tokens; `--debug-ollama` reports
`message_thinking_length` when smoke-checking this behavior.

`quiz-bench` uses the answer response budget by default so essay drafts can
complete. For MC-only timing runs, the compatibility `mc-bench` command still
uses a smaller response budget:

```text
--num-predict 32
--limit 3
--chars 300
```

Those defaults are deliberate: MC answers need only a structured option label,
and local CachyOS benchmarks found 300 characters per retrieved context chunk
about 31% faster than 900 characters with the same 90% accuracy on the fixed
20-question quiz. The next lower test, 225 characters, dropped accuracy to 85%.

Thread count is now exposed as an optional Ollama request option through
`ETHNOS_OLLAMA_NUM_THREAD`. On this host, the measured MC runs favored leaving
it unset. Use explicit values only for fresh A/B tests instead of assuming all
logical CPUs are fastest:

```bash
ETHNOS_OLLAMA_NUM_THREAD=4 uv run ethnos mc-bench 1 \
  --quiz data/runs/perf-quiz-medium-20.json \
  --num-ctx 4096 \
  --output data/runs/perf-threads4-ctx4096.json
```

## SQLite Settings

`ethnos.db.connect()` already applies pragmatic local SQLite settings:

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -32000;
PRAGMA temp_store = MEMORY;
PRAGMA mmap_size = 134217728;
```

For the current 11 MiB database, SQLite is not the bottleneck. Raising cache or
mmap settings would not be measurable for normal `search`, `context`,
`generate-quiz`, `validate-quiz`, or `quiz-bench` retrieval work.

Consider revisiting only when local databases are hundreds of MiB or when
profiling shows SQLite time dominating Ollama time. A future large-document
profile could test `cache_size=-131072` and `mmap_size=1073741824`, but those
should be evidence-based changes rather than defaults today.

## Swap And Memory

The host has enough RAM for the current CPU models and the current database.
zram swap is present, but idle swap usage is zero.

Monitor during long runs:

```bash
free -h
swapon --show
zramctl
```

Only consider lowering swappiness if zram usage grows during inference:

```bash
sudo sysctl vm.swappiness=20
```

This is not currently recommended as a default. With no swap pressure, it is a
distraction.

## Measurement Protocol

Use `quiz-bench` reports so speed changes are visible next to accuracy,
retrieval changes, unscored answers, and essay drafts. Use `mc-bench` plus
`mc-compare` when comparing MC-only reports.

Create or choose a fixed quiz:

```bash
uv run ethnos generate-quiz 1 \
  --source terms \
  --difficulty medium \
  --limit 20 \
  --seed 42 \
  --output data/runs/perf-quiz-medium-20.json
```

Run a current MC-only baseline:

```bash
uv run ethnos mc-bench 1 \
  --quiz data/runs/perf-quiz-medium-20.json \
  --num-ctx 8192 \
  --output data/runs/perf-baseline-mc.json
```

For mixed quizzes with essays, use `quiz-bench` and keep the larger default
context text unless a separate mixed-quiz benchmark proves a smaller value safe:

```bash
uv run ethnos quiz-bench 1 \
  --quiz data/runs/perf-quiz-medium-20.json \
  --output data/runs/perf-baseline-mixed.json
```

Apply one change, then run again. For example, test a shorter MC context:

```bash
uv run ethnos mc-bench 1 \
  --quiz data/runs/perf-quiz-medium-20.json \
  --num-ctx 8192 \
  --chars 225 \
  --output data/runs/perf-mc-chars225.json
```

Compare:

```bash
uv run ethnos mc-compare \
  data/runs/perf-baseline-mc.json \
  data/runs/perf-mc-chars225.json \
  --output data/runs/perf-compare-mc-chars225.json
```

What to watch:

- `elapsed_seconds` in each `quiz-bench` report.
- Per-item `timings.answer_seconds`.
- `accuracy`, no-context count, invalid-response count, and essay draft timings.
- `selected_chunks` and retrieval changes if accuracy moves.
- `ollama ps` to see whether the model was already resident.

Use at least two runs per configuration when possible. CPU inference has normal
run-to-run variance from thermals, background load, and model residency.

## Current CachyOS MC Results

These runs used `gemma-python`, `ETHNOS_OLLAMA_NUM_THREAD` unset, and the fixed
20-question `perf-quiz-medium-20.json` quiz unless noted otherwise.

| Run | Context Text | Elapsed | Avg Answer | Accuracy | Notes |
|---|---:|---:|---:|---:|---|
| baseline rerun | 900 chars | 15m 20s | 46.01s | 90% | Stable with original 8192 context |
| shorter context | 600 chars | 12m 39s | 37.95s | 90% | Same accuracy, different wrong pair |
| shorter context | 450 chars | 11m 49s | 35.42s | 90% | Same answers as 600 |
| current default | 300 chars | 10m 30s | 31.51s | 90% | Fastest safe MC setting tested |
| too short | 225 chars | 10m 10s | 30.48s | 85% | Accuracy cliff; do not use by default |
| `game-performance`, ctx4096 | 900 chars | 16m 21s | 49.05s | 90% | Slower |
| thread 4, ctx4096 | 900 chars | 16m 01s | 48.05s | 90% | Slower |
| thread 6, ctx4096 | 900 chars | 16m 09s | 48.47s | 90% | Slower |

Current conclusion: keep `ETHNOS_OLLAMA_NUM_CTX=8192`, leave
`ETHNOS_OLLAMA_NUM_THREAD` unset, avoid `game-performance` for this MC workload,
and use `mc-bench --chars 300`.

## What Not To Tune Blindly

- **Ollama thread count:** Avoid global thread overrides without a fresh A/B
  benchmark. Use `ETHNOS_OLLAMA_NUM_THREAD` for controlled tests, then leave it
  unset unless a value repeatedly wins.
- **Kernel VM parameters:** Do not change swappiness, dirty ratios, transparent
  huge pages, or scheduler knobs unless monitoring points to that specific
  bottleneck.
- **SQLite durability settings:** Keep WAL and `synchronous=NORMAL`. Avoid
  `synchronous=OFF` for normal project use.
- **Bigger context windows:** Larger `num_ctx` increases memory and compute.
  Raise it only when retrieval traces prove needed context is being truncated.

## Future Work

- Add a small `ethnos perf-smoke` command that runs a fixed quiz subset and
  prints tokens/second or answer-seconds summaries.
- Evaluate `quiz-bench --models` once implemented, because model choice may beat
  system tuning.
- Test controlled parallel structure extraction with one and two concurrent
  requests. This may reduce wall-clock time, but it could also hurt per-request
  latency or quality on a 4-core CPU.
- Revisit GPU acceleration if a supported dGPU or eGPU becomes available; that
  would likely dwarf CPU/kernel tuning.
