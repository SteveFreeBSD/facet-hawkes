# erosion

`erosion` is the current local development host.

## Snapshot

Observed on 2026-05-20:

| Area | Value |
|---|---|
| OS/kernel | Linux `7.0.9-zen1-1-zen` x86_64 |
| CPU | AMD Ryzen 7 PRO 5850U with Radeon Graphics |
| Cores/threads | 8 cores / 16 threads |
| Memory | 30 GiB RAM, 30 GiB swap |
| Ollama | 0.24.0, active systemd service |
| Ollama service env | `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_MLOCK=1` |
| Memlock | `LimitMEMLOCK=infinity` |
| Required model | `gemma-python:latest` |
| Extra local models | `gemma4:e2b`, `gemma-fast:latest`, `gemma4:e4b` |

## Notes

- The repo baseline only requires `gemma-python`.
- Extra models on this host are experimental local state, not project
  dependencies.
- `ETHNOS_OLLAMA_NUM_THREAD` should normally remain unset.
- Add `OLLAMA_KEEP_ALIVE=30m` only if repeated local runs are paying frequent
  cold-start load cost.

## Verification

```bash
hostname
uname -srmo
lscpu
free -h
ollama --version
ollama list
systemctl show ollama -p ActiveState -p SubState -p Environment -p LimitMEMLOCK
```
