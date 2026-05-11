# Performance Tuning

This guide captures local performance tuning for `ethnos` on the current
CPU-only development machine. Treat it as a measurement-driven playbook: apply
one change at a time, record the result, and keep reversible system changes out
of project defaults unless they prove stable.

## Quick Recommendations

1. Use the CPU `performance` governor during long Ollama runs, then switch back
   to `powersave` afterward.
2. Add `OLLAMA_KEEP_ALIVE=30m` to the Ollama systemd override so models stay
   resident between nearby runs.
3. Keep `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_MLOCK=1`, and
   `LimitMEMLOCK=infinity`; they are already part of the local baseline.
4. Do not force `num_thread=16` globally. It was slower on this Ryzen 7 PRO
   5850U in prior smoke checks.
5. Leave SQLite and swap tuning alone until monitoring shows real pressure.

## Current Host Snapshot

This snapshot was observed on the local development machine and should be
rechecked after OS, kernel, Ollama, or hardware changes.

| Component | Observed Value |
|---|---|
| OS/kernel | Garuda Linux, Zen kernel |
| CPU | AMD Ryzen 7 PRO 5850U, 8 cores / 16 threads |
| RAM | 62 GiB total, roughly 56 GiB available when idle |
| Storage | NVMe SSD |
| GPU for Ollama | None detected; inference is CPU-only |
| Ollama | 0.23.2 |
| Models | `gemma-python`/`gemma4:e2b` 7.2 GB, `gemma-fast`/`gemma4:e4b` 9.6 GB |
| CPU governor | `powersave` on all 16 logical CPUs |
| Swap | 62 GiB zram, no swap used at idle |
| Database | `data/ethnos.sqlite`, about 4 MiB |

Useful inspection commands:

```bash
lscpu
free -h
swapon --show
cat /proc/sys/vm/swappiness
cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor | sort | uniq -c
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

Known-good baseline:

```ini
[Service]
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_MLOCK=1"
LimitMEMLOCK=infinity
```

Recommended addition:

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

CPU-only Ollama is compute-bound. The current host uses `amd_pstate` with the
`powersave` governor. Boost is enabled, but sustained inference may still
benefit from explicitly switching to `performance`.

Enable performance mode:

```bash
sudo cpupower frequency-set -g performance
```

Revert when the run is done:

```bash
sudo cpupower frequency-set -g powersave
```

Verify:

```bash
cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor | sort | uniq -c
```

If `cpupower` is missing on this Arch/Garuda host, install the package that
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
    cpupower frequency-set -g powersave
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
```

`think=false` is intentional. Local Gemma models can spend the whole output
budget on hidden thinking tokens; `--debug-ollama` reports
`message_thinking_length` when smoke-checking this behavior.

`mc-bench` uses a smaller MC response budget by default:

```text
--num-predict 32
--limit 3
--chars 900
```

Those defaults are deliberate: MC answers need only a structured option label,
and tighter context usually helps reduce distractor bleed.

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

For the current 4 MiB database, SQLite is not the bottleneck. Raising cache or
mmap settings would not be measurable for normal `search`, `context`,
`generate-quiz`, `validate-mc-quiz`, or `mc-bench` retrieval work.

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

Use existing `mc-bench` and `mc-compare` reports so speed changes are visible
next to accuracy and retrieval changes.

Create or choose a fixed quiz:

```bash
uv run ethnos generate-quiz 1 \
  --source terms \
  --difficulty medium \
  --limit 20 \
  --seed 42 \
  --output data/runs/perf-quiz-medium-20.json
```

Run a baseline:

```bash
uv run ethnos mc-bench 1 \
  --quiz data/runs/perf-quiz-medium-20.json \
  --output data/runs/perf-baseline.json
```

Apply one change, then run again:

```bash
sudo cpupower frequency-set -g performance

uv run ethnos mc-bench 1 \
  --quiz data/runs/perf-quiz-medium-20.json \
  --output data/runs/perf-governor.json
```

Compare:

```bash
uv run ethnos mc-compare \
  data/runs/perf-baseline.json \
  data/runs/perf-governor.json \
  --output data/runs/perf-compare-governor.json
```

What to watch:

- `elapsed_seconds` in each `mc-bench` report.
- Per-item `timings.answer_seconds`.
- `accuracy` and correctness flips in `mc-compare`.
- `selected_chunks` and retrieval changes if accuracy moves.
- `ollama ps` to see whether the model was already resident.

Use at least two runs per configuration when possible. CPU inference has normal
run-to-run variance from thermals, background load, and model residency.

## Historical Local Baselines

These are local observations, not performance guarantees:

| Run | Items | Elapsed | Per Item |
|---|---:|---:|---:|
| `mc-bench-ethics-ch1-v6` | 10 | 90.6s | 9.1s |
| `mc-bench-terms-medium-20` | 20 | 264.7s | 13.2s |
| `mc-bench-terms-easy-20-v4` | 20 | 266.0s | 13.3s |
| `mc-bench-terms-easy-20` | 20 | 338.4s | 16.9s |
| `mc-bench-terms` | 10 | 231.3s | 23.1s |

For full structure extraction with `gemma-python` and a 2048-token extraction
budget, the latest observed 100-chunk run took about 146 minutes. Valid chunks
averaged around 60 seconds; validation-error chunks often wasted 2-3 minutes.

## What Not To Tune Blindly

- **Ollama thread count:** Prior local testing found `num_thread=16` slower on
  the Ryzen 7 PRO 5850U CPU path. Avoid global thread overrides without a fresh
  A/B benchmark.
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
- Evaluate `mc-bench --models` once implemented, because model choice may beat
  system tuning.
- Test controlled parallel structure extraction with one and two concurrent
  requests. This may reduce wall-clock time, but it could also hurt per-request
  latency or quality on an 8-core CPU.
- Revisit GPU acceleration if a supported dGPU or eGPU becomes available; that
  would likely dwarf CPU/kernel tuning.
