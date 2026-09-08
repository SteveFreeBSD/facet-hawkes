# Trace Debugging

> **Scope: the local study engine.** These traces come from `ask` and `chat`
> over ingested PDFs. A live Hawkes failure leaves different evidence -- see
> [Live Hawkes Observatory](LIVE_OBSERVATORY.md) and [Retained failure
> ledger](FAILURE_LEDGER.md).

Use answer traces when a grounded `ask` or `chat` response looks incomplete,
uncited, off-topic, or unexpectedly expensive. Traces are local JSON files and
are not written unless requested.

## Capture A Trace

```bash
uv run ethnos ask 1 "What is virtue ethics?" --trace-dir data/runs
uv run ethnos chat 1 --trace-dir data/runs
```

Each trace includes the original question, derived retrieval query, fallback
queries, selected chunks, citations, model settings, answer text, elapsed time,
and compact Ollama response diagnostics.

## Inspect A Trace

```bash
uv run ethnos inspect-trace data/runs/<trace-file>.json
uv run ethnos inspect-trace data/runs/<trace-file>.json --show-answer
```

Use the summary in this order:

1. Confirm `Context found` is `yes`. If it is `no`, debug retrieval with
   `uv run ethnos context <document_id> "<query>"`, then narrow or broaden with
   `--role`, `--section`, `--limit`, and `--chars`.
2. Check `Selected query` and fallback queries. If the selected query is too
   broad or too narrow, add a better retrieval question or use chat follow-up
   rewriting.
3. Review selected chunks and citations. For suspicious chunks, run
   `uv run ethnos inspect-chunk <document_id> <chunk_id> --records`.
4. Check Ollama response diagnostics. `done_reason=length` means the answer hit
   the output budget; increase `--num-predict` only after confirming retrieval
   is correct.
5. Check `thinking_chars`. The baseline expects `0` with
   `ETHNOS_OLLAMA_THINK=false`; nonzero hidden thinking can consume the output
   budget before the answer appears.

## Red Flags

- `Context found: no`: retrieval failed before Ollama was called.
- `Selected chunks: 0`: same as above; inspect query and role filters first.
- `done_reason=length`: output was truncated.
- `error` is not `None`: Ollama returned a response-level error.
- Selected chunks are `support`, `admin`, or `artifact` for a normal study
  question: re-run with the default `--role core` or verify section labels.
- Citations do not match the answer: inspect the selected chunks and compare the
  answer text against the retrieved context.

Keep trace files under `data/runs/` so they remain local ignored runtime data.
