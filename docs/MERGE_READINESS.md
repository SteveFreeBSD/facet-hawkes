# Merge Readiness

Snapshot for the current review branch as of 2026-07-11.

## Status

Local CI-equivalent checks are green:

```bash
uv sync --frozen --extra dev
uv run ruff check .
uv run ruff format --check .
uv run python -m compileall -q src tests
uv run vulture src tests --min-confidence 80
uv run pytest -q
git diff --check
```

Observed result:

- `ruff check`: passed.
- `ruff format --check`: 58 files already formatted.
- `compileall`: passed.
- `vulture`: clean.
- `pytest`: 211 passed.
- `git diff --check`: passed.
- `uv sync --frozen --extra dev`: checked 21 packages.

## Include These New Files

These untracked files are intentional and should be staged with the merge:

- `benchmarks/history_ch25_canvas_raw.txt`
- `benchmarks/history_ch25_canvas_answer_key.txt`
- `benchmarks/history_ch25_canvas.json`
- `docs/hosts/caspian-optimization-report-2026-07-11.md`
- `docs/MERGE_READINESS.md`

The Chapter 25 fixture was validated with:

```bash
uv run ethnos validate-quiz 2 \
  --quiz benchmarks/history_ch25_canvas.json \
  --require-anchors
```

Observed result: 20 questions validated, 0 errors.

## Host Runtime Profile

`caspian` is now the measured host profile for local Ollama benchmarks:

- CachyOS Linux `7.1.3-1-cachyos`.
- Ollama 0.31.1.
- `OLLAMA_FLASH_ATTENTION=1`.
- `OLLAMA_MLOCK=1`.
- `OLLAMA_KEEP_ALIVE=24h`.
- `LimitMEMLOCK=infinity`.
- `vm.min_free_kbytes=262144`.
- `scx_bpfland` Auto through enabled `scx_loader.service`.
- CPU governor remains `schedutil`.
- `ETHNOS_OLLAMA_NUM_THREAD` remains unset.

Post-reboot validation confirmed the profile returns after restart:

```bash
scxctl get
cat /sys/kernel/sched_ext/state
systemctl is-enabled scx_loader.service
systemctl is-active scx_loader.service
sysctl vm.min_free_kbytes
systemctl show ollama -p Environment -p LimitMEMLOCK -p ActiveState -p SubState
```

Expected highlights:

- `running Bpfland in Auto mode`.
- `enabled` sched-ext state.
- `scx_loader.service` enabled and active.
- `vm.min_free_kbytes = 262144`.
- Ollama active with the 24-hour keepalive profile.

## Benchmark Evidence

Primary MC reference:

- `data/runs/perf-caspian-bpfland-auto-repeat-20260711-mc.json`
- 20/20 accuracy.
- 38.947 seconds elapsed.
- 0 invalid responses.
- 0 no-context cases.

Mixed validation on the same host profile:

- `data/runs/perf-caspian-bpfland-mixed-warm-20260711.json`
- 19/20 grounded accuracy.
- 0 invalid responses.
- 0 no-context cases.
- Single miss: q0005, `source_status=invalid_anchor`.

The `data/runs/` reports are local runtime artifacts and remain ignored by git.
The committed documentation records their summaries and paths for reviewer
traceability.

## Reviewer Path

Start here:

1. [`CURRENT_BASELINE.md`](CURRENT_BASELINE.md) for the current app, benchmark,
   and host baseline.
2. [`PERFORMANCE_TUNING.md`](PERFORMANCE_TUNING.md) for the tuning protocol and
   chosen `caspian` profile.
3. [`hosts/caspian.md`](hosts/caspian.md) for the live host inventory,
   benchmark ladder, rollback notes, and reboot validation.
4. [`hosts/caspian-optimization-report-2026-07-11.md`](hosts/caspian-optimization-report-2026-07-11.md)
   for the full CachyOS/kernel audit.
5. [`../benchmarks/history_chapter_quizzes.md`](../benchmarks/history_chapter_quizzes.md)
   for the Chapter 25 fixture workflow and disputed-key note.

## Caveats

- The first warm MC run was a poor timing reference at 452.845 seconds. Use the
  hot-control default-scheduler run, 40.510 seconds, for scheduler comparisons.
- `scx_bpfland` Auto is only a small but repeatable win over the hot-control
  default scheduler on the MC benchmark.
- Fixed `ETHNOS_OLLAMA_NUM_THREAD=4` and `6` are much slower on this host.
- The mixed benchmark miss is documented as an invalid-anchor/content issue, not
  a scheduler or system tuning failure.
