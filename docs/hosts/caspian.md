# Caspian Host Profile

Last verified: 2026-07-16.

`caspian` is the primary Ethnos workstation and the source of the current
performance baseline.

## Hardware and platform

| Area | Current value |
|---|---|
| System | HP t740 Thin Client |
| BIOS | `M42 v01.23`, 2026-04-27 |
| OS | CachyOS |
| Kernel | `7.1.3-2-cachyos` |
| CPU | AMD Ryzen Embedded V1756B, 4 cores / 8 threads |
| Graphics | Integrated Radeon Vega 8, RADV/Raven Vulkan |
| Memory | 61 GiB usable RAM |
| Swap | 61.7 GiB zram, zstd |
| Storage | 1 TB WD_BLACK SN850P NVMe |
| Filesystem | btrfs, `noatime`, `compress=zstd:1`, `discard=async` |
| CPU governor | `schedutil` on all CPUs |
| Power profile | `balanced` |
| Clocksource | `hpet` |
| sched-ext | disabled; `scx_loader.service` disabled/inactive |

CPU boost is enabled. The active kernel uses its default scheduler; historical
`scx_bpfland` results were CPU-only and are no longer part of the live profile.

## Vulkan and Ollama

| Area | Current value |
|---|---|
| Ollama | `0.32.1` |
| Vulkan instance | `1.4.350` |
| Vulkan driver | Mesa RADV `26.1.5-arch3.1` |
| Required model | `gemma-python:latest` |
| Gemma runner | 100% GPU, context 4096, about 1.8 GB active allocation |
| Layer placement | 36/36 layers offloaded |
| Keepalive | 24 hours |

The firmware exposes about 1 GB of dedicated iGPU VRAM, while AMDGPU also
provides shared GTT memory from system RAM. Ollama's Vulkan runner uses that
shared-memory path successfully; increasing a BIOS UMA aperture is not required
for the accepted Gemma profile.

The active systemd drop-in is:

```text
/etc/systemd/system/ollama.service.d/override.conf
```

```ini
[Service]
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_IGPU_ENABLE=1"
Environment="OLLAMA_MLOCK=1"
Environment="OLLAMA_KEEP_ALIVE=24h"
LimitMEMLOCK=infinity
```

The staged image-question profile is checked in at
`deploy/systemd/ollama-ethnos.conf`. It shortens the fallback keepalive to 30
minutes, explicitly limits the host to two loaded models, and makes the existing
single-request parallelism explicit. Installing it requires administrator
authority:

```bash
sudo install -m 0644 deploy/systemd/ollama-ethnos.conf \
  /etc/systemd/system/ollama.service.d/override.conf
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

Ethnos also sends `ETHNOS_OLLAMA_KEEP_ALIVE` per request when configured, so
normal `.env`-driven screenshot sessions receive the 30-minute behavior before
the global service drop-in is promoted. Do not restart Ollama while a structure
run is active.

Apply after editing:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

Verify:

```bash
systemctl show ollama \
  -p ActiveState -p SubState -p Environment -p LimitMEMLOCK
ollama --version
ollama list
ollama ps
vulkaninfo --summary
```

Expected: active/running service, all four Ollama environment variables,
unlimited memlock, and `gemma-python` at `100% GPU` with context `4096`.

## Models

Installed tags:

```text
gemma-python:latest
qwen3-coder:30b
qwen3-coder-caspian:latest
qwen3-coder-caspian-dev:latest
```

Only `gemma-python` is required. The Qwen tags are optional, unloaded
experiments that share one approximately 18 GB model blob. They consume no
runtime GPU or RAM while absent from `ollama ps`.

The Qwen 30B MoE model can offload all 49 layers, but it is slower than Gemma
for Ethnos and sustained 8K tests triggered AMDGPU compute-ring resets. No
AMDGPU lockup-timeout override was installed; masking that instability would
not improve the accepted 4K Gemma workflow.

## Kernel and memory settings

Persistent sysctl profile:

```text
/etc/sysctl.d/99-ethnos-caspian.conf
```

Current values:

```text
vm.min_free_kbytes = 262144
vm.swappiness = 150
vm.vfs_cache_pressure = 50
vm.page-cluster = 0
vm.dirty_background_bytes = 67108864
vm.dirty_bytes = 268435456
vm.dirty_background_ratio = 0
vm.dirty_ratio = 0
```

The large zram device and CachyOS swappiness are intentional; final validation
showed zero swap use and more than 50 GiB available memory with Gemma loaded.
Do not change VM, THP, or dirty-page settings without a measured memory or I/O
bottleneck.

## Package trust state

The earlier package-signature failure was repaired by rebuilding the pacman
trust state and refreshing the distribution keyrings. Current verification:

```text
archlinux-keyring 1:20260707.1-1
cachyos-keyring 20240331-1
cachyos-mirrorlist 27-1
pacman -Dk: No database errors have been found
```

Recheck after a keyring or mirror problem with:

```bash
pacman -Q archlinux-keyring cachyos-keyring cachyos-mirrorlist
pacman -Dk
```

Do not disable package signature verification as a workaround.

## Accepted Ethnos profile

```text
model: gemma-python
context: 4096
think: false
num_thread: unset
MC excerpt: 300 characters
mixed excerpt: 900 characters
Ollama prompt batch: model default 512
```

Acceptance result: 20/20 correct, zero invalid responses, zero no-context
cases, 118.1 seconds including a cold load. See
[../PERFORMANCE_TUNING.md](../PERFORMANCE_TUNING.md) for the reproducible
decision record.

## Persistence and upgrades

| Setting | Persistence location |
|---|---|
| BIOS | Firmware NVRAM |
| Ollama acceleration/keepalive | systemd drop-in above |
| Memlock limit | systemd drop-in above |
| VM profile | `/etc/sysctl.d/99-ethnos-caspian.conf` |
| Ethnos defaults | tracked source and `.env.example` |
| Ollama models | `/var/lib/ollama` |
| Processed course data | ignored `data/` directory |

Normal application and kernel package upgrades should not overwrite the
systemd drop-in, sysctl file, Ollama model store, or tracked Ethnos defaults.
After Ollama, Mesa, kernel, or firmware upgrades, rerun the checks below because
runtime behavior can still change even when configuration files persist.

## Post-upgrade verification

```bash
uname -r
cat /sys/class/dmi/id/bios_version
ollama --version
systemctl show ollama -p ActiveState -p SubState -p Environment -p LimitMEMLOCK
systemctl is-enabled scx_loader.service
cat /sys/kernel/sched_ext/state
cat /sys/devices/system/clocksource/clocksource0/current_clocksource
ollama ps
free -h
swapon --show
uv run pytest -q
uv run ethnos ask 1 "What is virtue ethics?" --limit 2 --debug-ollama
```

If `ollama ps` no longer reports 100% GPU, use
[../OLLAMA_TROUBLESHOOTING.md](../OLLAMA_TROUBLESHOOTING.md).
