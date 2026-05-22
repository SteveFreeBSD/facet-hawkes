# Ollama Troubleshooting

Use this when an `ethnos` command reaches Ollama and the response looks empty,
truncated, invalid, or unavailable. The baseline remains local-only:
`gemma-python` at `http://localhost:11434`.

## Fast Inventory

```bash
ollama --version
ollama list
ollama ps
systemctl show ollama -p ActiveState -p SubState -p Environment -p LimitMEMLOCK
uv run ethnos ask 1 "What is virtue ethics?" --limit 2 --num-predict 256 --debug-ollama
```

Expected baseline:

- Ollama service is `active/running`.
- `gemma-python:latest` exists in `ollama list`.
- Service env includes `OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_MLOCK=1`.
- `LimitMEMLOCK=infinity`.
- The debug smoke reports `done_reason=stop`, `message_thinking_length=0`, and
  `error=None`.

## Missing Or Unloaded Model

Symptoms:

- `request_failed` validation status.
- Error text mentions that the model does not exist.
- `ollama list` does not show `gemma-python:latest`.

Checks:

```bash
ollama list
ollama show gemma-python
```

Fix by recreating the documented `gemma-python` alias from
[`MIGRATION.md`](MIGRATION.md#model-alias), or copy the existing Ollama model
store with ownership preserved.

## Server Unavailable

Symptoms:

- Connection refused, timeout, or no response.
- `systemctl show` is not active/running.

Checks:

```bash
systemctl status ollama
systemctl show ollama -p ActiveState -p SubState -p Environment -p LimitMEMLOCK
```

Fix:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

Then rerun the fast inventory smoke.

## Empty Response

Symptoms:

- Structured extraction stores `validation_status=empty_response`.
- Debug output shows `message_content_length=0`.

Checks:

```bash
uv run ethnos structure 1 --limit 1 --debug-ollama
```

If `message_thinking_length` is high while content is empty, keep
`ETHNOS_OLLAMA_THINK=false`. If the response is still empty, raise
`--num-predict` only for the failing command and rerun a one-chunk smoke before
touching a full document.

## Truncated Response

Symptoms:

- Debug output shows `done_reason=length`.
- CLI prints a warning that the answer hit the Ollama output length limit.

Fix:

```bash
uv run ethnos ask 1 "What is virtue ethics?" --limit 2 --num-predict 512 --debug-ollama
```

For structured extraction, increase `--num-predict` only after reproducing the
failure on `--chunk-id` or `--limit 1`.

## Invalid JSON

Symptoms:

- Structured or quiz response stores `invalid_json` or `validation_error`.
- Raw output contains prose, Markdown fences, or incomplete JSON.

Checks:

```bash
uv run ethnos structure 1 --limit 1 --debug-ollama
uv run ethnos quiz-bench 1 --quiz data/runs/smoke.json --debug-ollama
```

Keep `temperature=0`, keep schema titles, and avoid changing prompt/schema and
model/runtime knobs in the same pass. After changing storage policy, use
`refresh-records` to rebuild normalized rows from valid stored outputs without
recalling Ollama.

## Benchmark Safety

Do not use full `structure --force`, long quiz benchmarks, or multi-model
comparisons as first-line troubleshooting. Start with `ask --debug-ollama` and
one-chunk `structure` smokes, then escalate only after the cheap checks pass.
