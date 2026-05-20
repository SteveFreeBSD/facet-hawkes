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

## Current Tuning Decision

`caspian` produced the current MC benchmark default:

- `mc-bench --chars 300`
- `ETHNOS_OLLAMA_NUM_CTX=8192`
- `ETHNOS_OLLAMA_NUM_THREAD` unset
- `gemma-python`

The 300-character MC context was the fastest tested setting that preserved 90%
accuracy on the fixed 20-question benchmark. The 225-character run was a little
faster but dropped to 85%, so it is not a baseline setting.

## Verification

From another host:

```bash
ssh steve@192.168.0.133 'bash -lc "hostname; uname -srmo; lscpu; free -h; ollama --version; ollama list; systemctl show ollama -p ActiveState -p SubState -p Environment -p LimitMEMLOCK"'
```
