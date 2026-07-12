# caspian

`caspian` is the migrated CachyOS host at `192.168.0.133`.

## Snapshot

Observed on 2026-07-11:

| Area | Value |
|---|---|
| OS/kernel | CachyOS, Linux `7.1.3-1-cachyos` x86_64 |
| CPU | AMD Ryzen Embedded V1756B with Radeon Vega Gfx |
| Cores/threads | 4 cores / 8 threads |
| Memory | 62 GiB RAM, 62 GiB zram swap |
| GPU for Ollama | Integrated Radeon Vega present; Ollama currently runs CPU-only |
| CPU frequency driver/governor | `acpi-cpufreq`, `schedutil` |
| Power profile | `balanced` |
| sched-ext | `scx_bpfland` in `Auto` mode via enabled `scx_loader.service` |
| Ollama | 0.31.1, active systemd service |
| Ollama service env | `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_MLOCK=1`, `OLLAMA_KEEP_ALIVE=24h` |
| Memlock | `LimitMEMLOCK=infinity` |
| Required model | `gemma-python:latest` |
| Installed models | Only `gemma-python:latest` |

## Inventory (2026-07-11)

- `ollama --version`: 0.31.1.
- `ollama list`: `gemma-python:latest` (7.2 GB).
- `ollama ps`: `gemma-python:latest` resident during benchmark sessions,
  100% CPU, context `8192`, 24-hour keepalive.
- `systemctl show`: active/running, `LimitMEMLOCK=infinity`, environment line
  includes `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_MLOCK=1`, and
  `OLLAMA_KEEP_ALIVE=24h`.
- `uname -r`: `7.1.3-1-cachyos`.
- CPU driver/governor: `acpi-cpufreq`, `schedutil`.
- Available governors: `conservative`, `ondemand`, `userspace`, `powersave`,
  `performance`, `schedutil`.
- `powerprofilesctl get`: `balanced`.
- sched-ext packages installed: `scx-manager`, `scx-scheds`, and `scx-tools`.
- `scxctl list`: `beerland`, `bpfland`, `cake`, `cosmos`, `flash`, `flow`,
  `forge`, `lavd`, `pandemonium`, `p2dq`, `tickless`, `rustland`, `rusty`.
- `scxctl get`: `running Bpfland in Auto mode`.
- `scx_loader.service`: enabled and active.
- `/etc/scx_loader.toml`: `default_sched = "scx_bpfland"`,
  `default_mode = "Auto"`.
- `swapon --show`: `/dev/zram0` 62.2 GiB, negligible use.
- `zramctl`: zstd compression, 62.2 GiB disk size.
- `free -h`: 62 GiB total, 57 GiB available during the snapshot.
- VM state: MGLRU enabled (`0x0007`), THP `always`, `vm.swappiness=150`,
  `vm.vfs_cache_pressure=50`, `vm.page-cluster=0`,
  `vm.min_free_kbytes=262144`.
- Dirty page limits: byte-capped, with `vm.dirty_background_bytes=67108864`
  and `vm.dirty_bytes=268435456`; dirty ratios are disabled.
- KSM: available but disabled (`/sys/kernel/mm/ksm/run=0`).
- Static huge pages: not configured (`HugePages_Total=0`).
- tmpfs: `/tmp` and `/dev/shm` are each 31.1 GiB with `huge=advise`.
- Filesystem: btrfs on NVMe with `noatime`, `compress=zstd:1`, `ssd`,
  `discard=async`, `space_cache=v2`.
- I/O scheduler: NVMe uses `kyber`.
- Free-page reserve profile: `vm.min_free_kbytes=262144` (raised from kernel
  default ~90 MB to 256 MB
  via `/etc/sysctl.d/99-ethnos-caspian.conf`).
- Ananicy: `ananicy-cpp.service` active with CachyOS rules; startup log noted
  unavailable cgroup controls, though cgroup v2 controllers are present.

See [`caspian-optimization-report-2026-07-11.md`](caspian-optimization-report-2026-07-11.md)
for the 2026-07-11 kernel and resource optimization audit.

## Current Tuning Decision

`caspian` produced and now runs the current MC benchmark host profile:

- `mc-bench --chars 300`
- `ETHNOS_OLLAMA_NUM_CTX=8192`
- `ETHNOS_OLLAMA_NUM_THREAD` unset
- `gemma-python`
- `OLLAMA_KEEP_ALIVE=24h`
- `vm.min_free_kbytes=262144`
- `scx_bpfland` in `Auto` mode
- CPU governor remains `schedutil`

Use the generator's current `medium` filtering for source-of-truth MC runs. It
skips broad same-chunk sibling terms before benchmarking so the score reflects
model retrieval and answering rather than ambiguous quiz construction.

## 2026-07-11 Benchmark Results

All runs used `gemma-python`, `num_ctx=8192`, the fixed
`data/runs/perf-quiz-medium-20-current.json` quiz, warm Ollama residency, and
`mc-bench --chars 300` unless noted.

| Run | Result |
|---|---:|
| Initial warm baseline, default scheduler | 20/20, 452.845s |
| Hot control, default scheduler + `schedutil` | 20/20, 40.510s |
| `performance` governor | 20/20, 44.873s |
| `scx_lavd` Gaming | 20/20, 41.257s |
| `scx_flash` LowLatency | 20/20, 41.207s |
| `scx_bpfland` Auto | 20/20, 38.885s |
| `scx_bpfland` Auto repeat | 20/20, 38.947s |
| `scx_bpfland` Auto, `ETHNOS_OLLAMA_NUM_THREAD=4` | 20/20, 494.563s |
| `scx_bpfland` Auto, `ETHNOS_OLLAMA_NUM_THREAD=6` | 20/20, 463.580s |

Current winner: `scx_bpfland` Auto, `schedutil`, and
`ETHNOS_OLLAMA_NUM_THREAD` unset.

Mixed validation on the winning host profile:
`quiz-bench --chars 900` wrote
`data/runs/perf-caspian-bpfland-mixed-fixed-20260711.json`, with 20/20
grounded accuracy, 20/20 PDF-grounded source coverage, zero no-context cases,
zero invalid responses, and zero answer retries. The prior q0005 miss was
resolved by accepting structured key-term source-record anchors and using unique
option provenance guidance; the focused q0005 check is
`data/runs/perf-caspian-bpfland-mixed-q0005-after-20260711.json`.

Rollback notes:

- sched-ext: `sudo systemctl disable --now scx_loader.service`, then
  `sudo rm /etc/scx_loader.toml`.
- Ollama keepalive: edit
  `/etc/systemd/system/ollama.service.d/override.conf`, then
  `sudo systemctl daemon-reload && sudo systemctl restart ollama`.
- free-page reserve: `sudo rm /etc/sysctl.d/99-ethnos-caspian.conf && sudo sysctl --system`.

## Reboot Validation

Validated after reboot on 2026-07-11:

- Host booted `7.1.3-1-cachyos`.
- `scx_loader.service` returned as enabled and active.
- `scxctl get`: `running Bpfland in Auto mode`.
- `/sys/kernel/sched_ext/state`: `enabled`.
- CPU governors returned as `schedutil`.
- `powerprofilesctl get`: `balanced`.
- Ollama service returned active with `OLLAMA_FLASH_ATTENTION=1`,
  `OLLAMA_MLOCK=1`, `OLLAMA_KEEP_ALIVE=24h`, and `LimitMEMLOCK=infinity`.
- `vm.min_free_kbytes=262144` persisted.
- Dirty page byte caps persisted:
  `vm.dirty_background_bytes=67108864`, `vm.dirty_bytes=268435456`, ratios
  disabled.
- Post-reboot `ollama run gemma-python "hello" --verbose --keepalive 24h`
  loaded the model successfully. Cold load was 10.858s; `ollama ps` then showed
  `gemma-python:latest` resident for 24 hours.

## Verification

From another host:

```bash
ssh steve@192.168.0.133 'bash -lc "hostname; uname -srmo; lscpu; free -h; ollama --version; ollama list; systemctl show ollama -p ActiveState -p SubState -p Environment -p LimitMEMLOCK"'
```
