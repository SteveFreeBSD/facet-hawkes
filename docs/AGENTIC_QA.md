# Agentic Q&A

Agentic Q&A is the opt-in research-assistant mode for `ask` and `chat`. The
default Q&A path stays fast and fixed: retrieve context once, call the model
once, and answer. Agentic mode gives the model a bounded local-PDF tool loop so
it can search, inspect chunks or pages, and then finalize from the evidence it
actually found.

## Commands

```bash
uv run ethnos ask 1 "What is virtue ethics?" --agentic --trace-dir data/runs

uv run ethnos chat 1 --agentic --trace-dir data/runs
```

Useful options:

- `--agentic`: enable the structured local-PDF agent loop.
- `--agent-max-steps 4`: cap model/tool turns before falling back to fixed Q&A.
- `--trace-dir`: write the agent actions and tool results into the local trace.

## V1 Scope

V1 is local-PDF-only. The allowed tools are:

- `search_pdf`
- `inspect_chunk`
- `inspect_page`

Web, vision, page rendering, and quiz-specific tools are intentionally excluded
from Q&A v1. Native Ollama tool calling is also deferred; the implementation
uses the same structured JSON action-loop style as Agent Review because it is
more predictable with the current local `qwen3.5:9b` baseline.

## Fallback Behavior

If the agent loop cannot produce a valid final answer within the step budget,
`ask` and `chat` fall back to the existing fixed Q&A pipeline. The fixed path
remains the benchmark baseline and compatibility target.

Normal terminal output stays clean: question, answer, and sources. When
`--trace-dir` is provided, the trace JSON includes an `agentic` block with the
action sequence, tool results, source status, and fallback reason.
