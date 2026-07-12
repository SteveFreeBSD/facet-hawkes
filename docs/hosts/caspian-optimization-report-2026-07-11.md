# caspian Optimization Report - 2026-07-11

This report revisits the Ethnos optimization plan on `caspian` after the
CachyOS kernel moved to `7.1.3-1-cachyos`. It began as a read-only system audit;
the benchmark-session Ollama keepalive, free-page reserve, and winning
`scx_bpfland` scheduler recommendations were applied later on 2026-07-11.

## Executive Summary

`caspian` is already using the strongest default CachyOS kernel path for this
workload: `linux-cachyos` with Clang/ThinLTO and AutoFDO. The system also has
the expected CachyOS memory defaults for a large-RAM desktop: zram, high
swappiness for compressed swap, low VFS cache pressure, MGLRU, fixed dirty-byte
limits, btrfs compression, and `noatime`.

The largest practical gains came from:

1. Keeping Ollama resident with `OLLAMA_KEEP_ALIVE=24h`.
2. Enabling `scx_bpfland` in Auto mode through `scx_loader`.
3. Keeping `ETHNOS_OLLAMA_NUM_THREAD` unset.

The larger initial improvement was warm-session behavior: the first warm
baseline took 452.845s, while the hot default-scheduler control took 40.510s.
The scheduler win is smaller but repeatable: `scx_bpfland` Auto ran the MC
benchmark in 38.885s and 38.947s.

Recommendations retained from the audit:

1. Keep `linux-cachyos`; do not switch kernels without a fresh benchmark.
2. Keeping Ollama resident for benchmark sessions with `OLLAMA_KEEP_ALIVE=24h`
   or `-1` for dedicated benchmark days.
3. Keeping `vm.min_free_kbytes=262144` for extra allocator headroom while a
   7.2 GB model can be mlocked.
4. Avoiding memory and SQLite over-tuning until profiling shows they matter.

Do not switch to the CachyOS server kernel for the normal Ethnos workstation
workflow without benchmarking. CachyOS documents the default kernel as the
recommended kernel, with 1000 Hz tickrate, Clang/ThinLTO, and AutoFDO, while the
server variant trades toward 300 Hz, no preemption, and stock EEVDF.

## Current System Inventory

| Area | Current value |
|---|---|
| Host | `caspian` |
| OS | CachyOS |
| Kernel | `7.1.3-1-cachyos` |
| CPU | AMD Ryzen Embedded V1756B with Radeon Vega Gfx |
| CPU layout | 4 cores / 8 threads, SMT on, single NUMA node |
| RAM | 62 GiB total, 57 GiB available during audit |
| Swap | `/dev/zram0`, 62.2 GiB, zstd, priority 100 |
| Minimum free memory | `vm.min_free_kbytes=262144` |
| Watermarks | `vm.watermark_scale_factor=10`, `vm.watermark_boost_factor=0` |
| Dirty page limits | background 64 MiB, hard 256 MiB, ratio knobs disabled |
| CPU frequency | `acpi-cpufreq`, `schedutil`, 1.6/2.3/3.25 GHz advertised states |
| Power profile | `balanced` |
| sched-ext | `scx_bpfland` Auto, enabled through `scx_loader.service` |
| Ananicy | `ananicy-cpp.service` active with CachyOS rules |
| Ollama | 0.31.1, service active |
| Ollama env | `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_MLOCK=1`, `OLLAMA_KEEP_ALIVE=24h` |
| Ollama model | `gemma-python:latest`, 7.2 GB, idle during audit |
| Ethnos DB | 12 MiB SQLite database, whole `data/` tree 15 MiB |
| THP | `always`; defrag `defer+madvise`; shmem `advise` |
| KSM | Available but disabled: `/sys/kernel/mm/ksm/run=0` |
| Static huge pages | None configured: `HugePages_Total=0` |
| tmpfs | `/tmp` and `/dev/shm` are each 31.1 GiB with `huge=advise` |
| Root FS | btrfs on NVMe, `noatime`, `compress=zstd:1`, `discard=async` |
| NVMe scheduler | `kyber` |

## Applied Runtime Profile

Applied on 2026-07-11:

```ini
# /etc/systemd/system/ollama.service.d/override.conf
[Service]
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_MLOCK=1"
Environment="OLLAMA_KEEP_ALIVE=24h"
LimitMEMLOCK=infinity
```

```text
# /etc/sysctl.d/99-ethnos-caspian.conf
vm.min_free_kbytes = 262144
```

```toml
# /etc/scx_loader.toml
default_sched = "scx_bpfland"
default_mode = "Auto"
```

`scx_loader.service` is enabled and active. `scxctl get` reports
`running Bpfland in Auto mode`; `/sys/kernel/sched_ext/state` reports
`enabled`. CPU governors remain `schedutil`.

Post-reboot validation on 2026-07-11 confirmed the same profile returned after
a restart: `scx_loader.service` enabled/active, `scx_bpfland -m auto` running,
`vm.min_free_kbytes=262144`, Ollama active with `OLLAMA_KEEP_ALIVE=24h`, and
CPU governors at `schedutil`. A post-reboot `ollama run gemma-python "hello"
--verbose --keepalive 24h` successfully reloaded the model with a 10.858s cold
load, after which `ollama ps` showed the model resident for 24 hours.

Rollback:

```bash
sudo systemctl disable --now scx_loader.service
sudo rm /etc/scx_loader.toml
sudo rm /etc/sysctl.d/99-ethnos-caspian.conf
sudo sysctl --system
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

Edit the Ollama drop-in separately if rolling `OLLAMA_KEEP_ALIVE` back from
`24h` to `30m`.

## Already Good - Keep

- Keep `linux-cachyos` as the primary kernel for now. CachyOS documents it as
  the recommended default, built with Clang/ThinLTO and AutoFDO.
- Keep the Ollama service override: flash attention, mlock, memlock infinity,
  and `OLLAMA_KEEP_ALIVE=24h`.
- Keep `ETHNOS_OLLAMA_NUM_CTX=8192` and leave `ETHNOS_OLLAMA_NUM_THREAD`
  unset for normal runs. Existing project notes say Ollama's own scheduler beat
  fixed `4` or `6` thread settings on this host.
- Keep zram. It is barely used right now, but it is a good safety net and
  matches CachyOS-style memory behavior.
- Keep btrfs `compress=zstd:1`, `noatime`, and `discard=async`.
- Keep SQLite WAL and `synchronous=NORMAL`; the 12 MiB database is far too
  small to justify aggressive durability or cache changes.
- Keep the dirty page byte caps. CachyOS has applied byte-based limits here:
  `vm.dirty_background_bytes=67108864` and `vm.dirty_bytes=268435456`, with
  `vm.dirty_background_ratio=0` and `vm.dirty_ratio=0`. This avoids the
  multi-GiB dirty-page buffering risk that ratio defaults can create on a
  64 GiB system.

## Best Optimization Candidates

### 1. Keep Ollama resident during benchmark sessions

Status: applied for benchmark sessions.

`OLLAMA_KEEP_ALIVE=24h` is now active. The previous `30m` value was fine for
ordinary interactive use, but too conservative for benchmark ladders on this
64 GiB host. After loading the
7.2 GB model, the system still has enough RAM for the model, file cache, and
desktop processes. Cold model reloads waste time and make benchmark comparisons
noisy.

Recommendation:

- Use `OLLAMA_KEEP_ALIVE=-1` for dedicated benchmark sessions.
- Use `OLLAMA_KEEP_ALIVE=24h` if a finite benchmark-day value is preferred.
- Record `ollama ps` before every run so cold and warm timings stay separate.

Use `30m` only when the goal is to release model memory between normal desktop
sessions.

### 2. Raise `vm.min_free_kbytes`

Status: applied safe stability profile.

The current value is:

```text
vm.min_free_kbytes = 262144
```

This raises the previous roughly 66 MiB reserve to 256 MiB. With
`OLLAMA_MLOCK=1` and `LimitMEMLOCK=infinity`, a resident 7.2 GB model can reduce
reclaimable memory flexibility. The higher free reserve gives the allocator more
breathing room without meaningfully reducing usable RAM.

Adopt if memory PSI, Ollama stability, and benchmark behavior are unchanged or
better. This is a stability/headroom tweak, not a throughput tweak.

### 3. sched-ext A/B test

Status: completed for the MC benchmark ladder.

Evidence:

- `/sys/kernel/sched_ext/state`: `enabled`.
- `scx_loader.service`: enabled/active.
- `/etc/scx_loader.toml`: defaults to `scx_bpfland` Auto.
- `scxctl list`: `beerland`, `bpfland`, `cake`, `cosmos`, `flash`, `flow`,
  `forge`, `lavd`, `pandemonium`, `p2dq`, `tickless`, `rustland`, `rusty`.
- CachyOS documents sched-ext as a way to load schedulers dynamically without
  rebuilding the kernel, and stopping one returns to the default scheduler.

Test these first:

- Baseline: current default scheduler, `schedutil`, balanced profile.
- `scx_lavd --performance` or `scxctl start --sched lavd --mode gaming`.
- `scx_bpfland` server-ish/throughput mode only if MC benchmarks are CPU-bound.
- `scx_flash` for latency/responsiveness under desktop load.

Measure with the existing Ethnos benchmark protocol, not only generic CPU
benchmarks:

```bash
ollama ps
uv run ethnos mc-bench 1 \
  --quiz data/runs/perf-quiz-medium-20-current.json \
  --chars 300 \
  --num-ctx 8192 \
  --output data/runs/perf-caspian-default-20260711-mc.json
```

Then start one scheduler, rerun the same command with a different output file,
and compare:

```bash
uv run ethnos mc-compare \
  data/runs/perf-caspian-default-20260711-mc.json \
  data/runs/perf-caspian-lavd-performance-20260711-mc.json \
  --output data/runs/perf-caspian-lavd-compare-20260711.json
```

Result: `scx_bpfland` Auto won the MC benchmark without accuracy, invalid
response, no-context, answer, or retrieval regressions.

### 3a. 2026-07-11 Benchmark Ladder

All MC runs used `gemma-python`, `num_ctx=8192`,
`data/runs/perf-quiz-medium-20-current.json`, warm Ollama residency, and
`mc-bench --chars 300`.

| Profile | Report | Accuracy | Invalid | No context | Elapsed |
|---|---|---:|---:|---:|---:|
| Initial warm baseline, default scheduler | `perf-caspian-baseline-warm-20260711-mc.json` | 100% | 0 | 0 | 452.845s |
| Hot control, default scheduler + `schedutil` | `perf-caspian-schedutil-hot-control-20260711-mc.json` | 100% | 0 | 0 | 40.510s |
| `performance` governor | `perf-caspian-performance-governor-warm-20260711-mc.json` | 100% | 0 | 0 | 44.873s |
| `scx_lavd` Gaming | `perf-caspian-lavd-gaming-warm-20260711-mc.json` | 100% | 0 | 0 | 41.257s |
| `scx_flash` LowLatency | `perf-caspian-flash-lowlatency-warm-20260711-mc.json` | 100% | 0 | 0 | 41.207s |
| `scx_bpfland` Auto | `perf-caspian-bpfland-auto-warm-20260711-mc.json` | 100% | 0 | 0 | 38.885s |
| `scx_bpfland` Auto repeat | `perf-caspian-bpfland-auto-repeat-20260711-mc.json` | 100% | 0 | 0 | 38.947s |
| `scx_bpfland`, `ETHNOS_OLLAMA_NUM_THREAD=4` | `perf-caspian-bpfland-num-thread-4-20260711-mc.json` | 100% | 0 | 0 | 494.563s |
| `scx_bpfland`, `ETHNOS_OLLAMA_NUM_THREAD=6` | `perf-caspian-bpfland-num-thread-6-20260711-mc.json` | 100% | 0 | 0 | 463.580s |

Comparison reports:

- `perf-caspian-performance-vs-schedutil-hot-compare-20260711.json`
- `perf-caspian-lavd-vs-schedutil-hot-compare-20260711.json`
- `perf-caspian-flash-vs-schedutil-hot-compare-20260711.json`
- `perf-caspian-bpfland-vs-schedutil-hot-compare-20260711.json`
- `perf-caspian-bpfland-thread4-compare-20260711.json`
- `perf-caspian-bpfland-thread6-compare-20260711.json`

Mixed validation on the winning host profile:

- `perf-caspian-bpfland-mixed-fixed-20260711.json`
- `quiz-bench --chars 900`
- Grounded accuracy: 20/20 (100.0%)
- PDF-grounded source coverage: 20/20 (100.0%)
- Invalid responses: 0
- No-context cases: 0
- Answer retries: 0

The prior `perf-caspian-bpfland-mixed-warm-20260711.json` run missed q0005
with `source_status=invalid_anchor`. That was a benchmark grounding issue rather
than a scheduler issue: the stored `key_terms` record for `normative ethics`
validly points at chunk 10, while the chunk text phrases it as the
`"normative" or "prescriptive"` side of philosophical ethics. The validator now
accepts matching structured key-term source-record anchors, and mixed prompts
use unique option provenance guidance when one option maps to the requested
source record.

### 4. CPU governor/profile benchmark

Status: tested and rejected for the current MC profile.

This CPU is using `acpi-cpufreq`, not `amd-pstate`, so the newer AMD p-state EPP
and preferred-core knobs are not available here. The simple useful test is:

- Current: `schedutil` with `powerprofilesctl` set to `balanced`.
- Candidate: `performance` governor or performance power profile during timed
  Ethnos runs.

The direct `performance` governor test finished in 44.873s, slower than the
40.510s hot-control `schedutil` run and the 38.9s `scx_bpfland` runs. Keep
`schedutil`.

### 5. Revisit SQLite mmap/cache only after data grows

Status: not useful today.

The app applies `cache_size=-32000`, `temp_store=MEMORY`, and
`mmap_size=134217728` on its own connections. The current database is 12 MiB,
so SQLite is not consuming meaningful time or RAM. If the database grows into
hundreds of MiB or profiling shows SQLite time, then test a larger mmap such as
512 MiB or 1 GiB. Until then, larger SQLite cache values mostly decorate the
config file.

## Resource-Saving Candidates

- Stop Bluetooth, CUPS, Avahi, or desktop services only if this box becomes a
  dedicated Ethnos appliance. Current idle memory pressure is effectively zero,
  so service trimming will save little beyond background noise.
- Browser and editor processes were the top memory users during the audit, but
  RAM pressure was still low. Close them for clean benchmarks, not because the
  machine needs memory.
- Generic video/transcode activity can fully occupy cores. Do not benchmark
  Ethnos while such jobs are active.

## Avoid For Now

- Do not lower swappiness just because the system has 64 GiB RAM. With zram,
  high swappiness is intentional and current swap use is negligible.
- Do not disable THP blindly. THP is currently `always`, and there was no memory
  pressure or latency evidence pointing at THP stalls.
- Do not enable KSM for Ethnos/Ollama by default. It is disabled now and is more
  useful for VM/container page sharing than this single local model workflow.
- Do not reserve static huge pages for Ollama unless profiling or upstream
  guidance shows a real gain; static huge pages would remove memory from normal
  page cache/reclaim use.
- Do not move Ethnos runtime data to tmpfs. `/tmp` and `/dev/shm` already have
  large 31.1 GiB tmpfs mounts for scratch workloads, while the current SQLite
  DB is tiny and safe on NVMe.
- Do not replace zram with disk swap.
- Do not switch to `linux-cachyos-server` as a first move. It may improve some
  throughput workloads, but it gives up preemption and the 1000 Hz desktop
  tuning that fits interactive Ollama use.
- Do not pin `ETHNOS_OLLAMA_NUM_THREAD`: `4` and `6` were retested on Ollama
  0.31.1 with `scx_bpfland` and were much slower than leaving it unset.
- Do not install extra local models on this host unless they are part of a
  planned benchmark.

## Suggested Benchmark Ladder

Run this ladder in order. Change one variable at a time.

1. Current default: default scheduler, `schedutil`, balanced profile, warm and
   cold Ollama runs separated.
2. Benchmark-session Ollama residency: `OLLAMA_KEEP_ALIVE=-1` or `24h`.
3. `vm.min_free_kbytes=262144`.
4. Current default plus closed browser/editor/video work for a clean CPU test.
5. `performance` governor/profile with default scheduler.
6. `scx_lavd` performance/gaming mode.
7. `scx_flash` default or low-latency mode.
8. `scx_bpfland` default, then server mode only if throughput improves.
9. Re-test `ETHNOS_OLLAMA_NUM_THREAD=4`, `6`, and unset on Ollama 0.31.1.
10. Only after a winner appears, run mixed `quiz-bench --chars 900`.

Success criteria:

- Equal or better accuracy.
- Zero new invalid responses.
- Zero new no-context cases.
- Lower elapsed time or average answer seconds.
- No desktop stalls under normal use.

## Sources Checked

- Local system commands: `uname -a`, `lscpu`, `free -h`, `swapon --show`,
  `zramctl`, `sysctl`, THP/MGLRU sysfs files, `lsblk`, `findmnt`, `scxctl`,
  `systemctl`, `ollama`, `pacman`, and Ethnos docs/data inspection.
- CachyOS kernel documentation:
  <https://wiki.cachyos.org/features/kernel/>
- CachyOS sched-ext documentation:
  <https://wiki.cachyos.org/configuration/sched-ext/>
- CachyOS performance overview:
  <https://wiki.cachyos.org/cachyos_basic/why_cachyos/>
