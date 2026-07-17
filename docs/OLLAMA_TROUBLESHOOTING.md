# Ollama Troubleshooting

The supported local baseline is `gemma-python` at
`http://localhost:11434`, context `4096`, thinking disabled, and Vulkan
acceleration on `caspian`.

## Fast inventory

```bash
ollama --version
ollama list
ollama ps
systemctl show ollama -p ActiveState -p SubState -p Environment -p LimitMEMLOCK
vulkaninfo --summary
free -h
swapon --show
uv run ethnos ask 1 "What is virtue ethics?" --limit 2 --debug-ollama
```

Expected on `caspian`:

- Ollama `0.32.1`, active/running.
- `gemma-python:latest` exists.
- Service environment includes `OLLAMA_FLASH_ATTENTION=1`,
  `OLLAMA_IGPU_ENABLE=1`, `OLLAMA_MLOCK=1`, and
  `OLLAMA_KEEP_ALIVE=24h`.
- `LimitMEMLOCK=infinity`.
- `ollama ps` reports Gemma at `100% GPU`, context `4096`.
- The Ethnos smoke ends with `done_reason=stop`, no hidden thinking, and no API
  error.

## Model missing

Symptoms: `request_failed`, “model not found,” or no `gemma-python` in
`ollama list`.

```bash
ollama show gemma-python
```

Recreate the alias using [MIGRATION.md](MIGRATION.md#5-recreate-the-gemma-alias).
Qwen tags are not substitutes for the required Gemma alias.

## Service unavailable

Symptoms: connection refused, timeout before model loading, or an inactive
service.

```bash
systemctl status ollama
sudo systemctl daemon-reload
sudo systemctl restart ollama
journalctl -u ollama --since '-10 minutes' --no-pager
```

Rerun the fast inventory after restart.

## Gemma falls back to CPU

Symptoms: `ollama ps` shows `100% CPU`, generation is much slower, or Ollama
logs do not mention a Vulkan device.

Check:

```bash
systemctl show ollama -p Environment -p LimitMEMLOCK
vulkaninfo --summary
journalctl -u ollama --since '-10 minutes' --no-pager | \
  rg -i 'vulkan|offload|gpu|amdgpu|error'
```

On `caspian`, confirm `OLLAMA_IGPU_ENABLE=1`, a working RADV device, and
unlimited memlock. Restart Ollama after changing the drop-in. A successful Gemma
load logs `offloaded 36/36 layers to GPU`.

The iGPU uses shared system memory. A small firmware VRAM aperture does not by
itself mean Vulkan offload failed.

## Empty visible response

Symptoms: `validation_status=empty_response` or
`message_content_length=0`.

```bash
uv run ethnos structure 1 --limit 1 --debug-ollama
```

If `message_thinking_length` is nonzero, restore
`ETHNOS_OLLAMA_THINK=false`. Increase `--num-predict` only after reproducing the
failure on one chunk or one question.

## Truncated response

Symptoms: `done_reason=length` or a CLI output-limit warning.

```bash
uv run ethnos ask 1 "What is virtue ethics?" \
  --limit 2 --num-predict 512 --debug-ollama
```

Raise the budget only for the affected workflow. Larger output budgets do not
improve a response already ending with `done_reason=stop`.

## Invalid structured output

Symptoms: `invalid_json`, `validation_error`, Markdown fences, or incomplete
JSON.

```bash
uv run ethnos structure 1 --limit 1 --debug-ollama
uv run ethnos quiz-bench 1 --quiz data/runs/smoke.json --debug-ollama
```

Keep temperature `0` for quiz answers, keep schema metadata, and change only
one of model, prompt, schema, or runtime settings at a time. Use
`refresh-records` to rebuild normalized rows from already-valid stored outputs
without calling Ollama.

## Vulkan device lost or AMDGPU reset

Symptoms: request failure, `ErrorDeviceLost`, `ring comp_* timeout`, or a model
runner terminated by the kernel.

```bash
journalctl -u ollama --since '-15 minutes' --no-pager | \
  rg -i 'ErrorDeviceLost|decode.*failed|terminated'
journalctl -k --since '-15 minutes' --no-pager | \
  rg -i 'amdgpu|ring|timeout|reset|fault'
```

Stop the failing model and return to `gemma-python` at context `4096`. Do not
increase `amdgpu.lockup_timeout` merely to hide a repeatable model workload
failure. The Qwen 30B sustained 8K experiment produced this condition; the
accepted Gemma profile did not.

```bash
ollama stop qwen3-coder-caspian
ollama stop qwen3-coder-caspian-dev
ollama run gemma-python "Reply exactly: Gemma ready"
```

## Memory pressure

```bash
free -h
swapon --show
ollama ps
```

An unloaded Ollama model consumes disk only. Stop optional runners before
changing VM settings. On `caspian`, Gemma normally leaves more than 50 GiB
available and does not use swap.

## Benchmark results look impossibly fast

Ollama prompt cache can survive across aliases sharing the same weights. A run
that immediately follows an identical prompt may not be comparable.

```bash
ollama stop MODEL_NAME
```

Stop the runner between cold candidates and record cold/warm state in the
report name. Use the full protocol in
[PERFORMANCE_TUNING.md](PERFORMANCE_TUNING.md).

## Escalation order

1. Read-only inventory.
2. One `ask --debug-ollama` request.
3. One-chunk `structure` or one-item quiz smoke.
4. Focused kernel/Ollama logs.
5. Full acceptance benchmark only after the small smoke is stable.

Do not begin troubleshooting with `structure --force`, a full Agent Review, or
a multi-model comparison.
