# caspian

`caspian` is the migrated CachyOS host at `192.168.0.133`.

## Snapshot

Observed on 2026-05-20:

| Area | Value |
|---|---|
| OS/kernel | CachyOS, Linux `7.0.9-1-cachyos` x86_64 |
| CPU | AMD Ryzen Embedded V1756B with Radeon Vega Gfx |
| Cores/threads | 4 cores / 8 threads |
| Memory | 62 GiB RAM, 62 GiB zram swap |
| GPU for Ollama | Integrated Radeon Vega present; Ollama currently runs CPU-only |
| Ollama | 0.24.0, active systemd service |
| Ollama service env | `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_MLOCK=1`, `OLLAMA_KEEP_ALIVE=30m` |
| Memlock | `LimitMEMLOCK=infinity` |
| Required model | `gemma-python:latest` |
| Installed models | Only `gemma-python:latest` |

## Inventory (2026-05-20)

- `ollama --version`: 0.24.0.
- `ollama list`: `gemma-python:latest` (7.2 GB).
- `ollama ps`: no active models resident.
- `systemctl show`: active/running, `LimitMEMLOCK=infinity`, environment line
	includes `OLLAMA_FLASH_ATTENTION` and `OLLAMA_MLOCK` (see service override).
- `uname -r`: `7.0.9-1-cachyos`.
- CPU governor: `schedutil`.
- `swapon --show`: `/dev/zram0` 62.2 GiB, 1.1 MiB used.
- `free -h`: 62 GiB total, 7.6 GiB used, 54 GiB available.

## Current Tuning Decision

`caspian` produced the current MC benchmark defaults:

- `mc-bench --chars 300`
- `ETHNOS_OLLAMA_NUM_CTX=8192`
- `ETHNOS_OLLAMA_NUM_THREAD` unset
- `gemma-python`

Use the generator's current `medium` filtering for source-of-truth MC runs. It
skips broad same-chunk sibling terms before benchmarking so the score reflects
model retrieval and answering rather than ambiguous quiz construction.

## Verification

From another host:

```bash
ssh steve@192.168.0.133 'bash -lc "hostname; uname -srmo; lscpu; free -h; ollama --version; ollama list; systemctl show ollama -p ActiveState -p SubState -p Environment -p LimitMEMLOCK"'
```
