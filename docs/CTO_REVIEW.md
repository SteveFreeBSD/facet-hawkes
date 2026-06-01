# CTO Review

This is the concise review packet for `ethnos`: what the repo is, what is
authoritative, what was verified, and how future changes should stay aligned.

## Source Of Truth

- Runtime command surface: `uv run ethnos --help`.
- App/data baseline: [`CURRENT_BASELINE.md`](CURRENT_BASELINE.md).
- Ollama and benchmark policy: [`PERFORMANCE_TUNING.md`](PERFORMANCE_TUNING.md).
- Ollama troubleshooting: [`OLLAMA_TROUBLESHOOTING.md`](OLLAMA_TROUBLESHOOTING.md).
- Suspicious answer debugging: [`TRACE_DEBUGGING.md`](TRACE_DEBUGGING.md).
- Agentic model review: [`AGENT_REVIEW.md`](AGENT_REVIEW.md).
- Agentic Q&A: [`AGENTIC_QA.md`](AGENTIC_QA.md).
- Code review and bug findings: [`CODE_REVIEW.md`](CODE_REVIEW.md).
- Migration procedure: [`MIGRATION.md`](MIGRATION.md).
- Host-specific facts: [`hosts/`](hosts/).
- Environment defaults: [`.env.example`](../.env.example) and
  [`src/ethnos/config.py`](../src/ethnos/config.py).
- Curated GitHub-facing outputs: [`examples/`](../examples/).

## Repo Shape

- Python uses a `src/` layout with package code under [`src/ethnos`](../src/ethnos).
- The public interface is a CLI, not a web API. There are 39 registered
  subcommands and no FastAPI/Flask route layer.
- Core storage is SQLite with FTS5. [`db.py`](../src/ethnos/db.py) is the public
  facade; implementation is split across `db_core`, `db_sections`,
  `db_outputs`, `db_query`, `db_structure`, and `db_reports`.
- Schema validation is Pydantic v2 in [`models.py`](../src/ethnos/models.py) and
  quiz-specific models in `quiz_core`.
- [`quiz.py`](../src/ethnos/quiz.py) is the public quiz facade; implementation
  is split across `quiz_core`, `quiz_importers`, `quiz_prompts`, and
  `quiz_generation`.
- CLI answer retrieval uses a shared helper in `cli/retrieval.py`; quiz
  manifest validation lives in `cli/quiz_manifest.py`; quiz grounding and
  answer-key audit helpers live in `cli/quiz_audit.py`.
- Ollama calls are centralized in
  [`ollama_client.py`](../src/ethnos/ollama_client.py), using the current
  Python client `Client.chat(...)` API with JSON-schema `format`, request
  `options`, response-summary diagnostics, exponential retry backoff, and
  validation statuses.
- Agent Review is the flagship model-driven layer: it lets the measured
  CPU-local `gemma-python` alias or explicitly hybrid Ollama models call
  deterministic Ethnos tools, inspect PDF evidence, critique answer keys, score
  evidence strength/confidence, audit distractors, and emit auditable
  Markdown/JSON review queues.
- Agentic Q&A brings the same local-PDF tool-loop idea to `ask` and `chat` as
  an opt-in mode. It can call read-only search/inspect tools before answering,
  writes trace details when requested, and falls back to fixed Q&A if the loop
  cannot finalize.

## Current Verification

Observed on 2026-06-01:

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed.
- `uv run python -m compileall -q src tests`: passed.
- `uv run pytest`: 201 passed.
- Dead-code scan with Vulture at 80% confidence: clean and enforced in CI.
- CPU-local Agent Review probe for History chapter 20: `20` keyed answers
  supported, `17` pass items, `3` inspect items, duplicate prompt and spelling
  findings preserved.
- Live Ollama smoke: `ask` retrieved core ethics chunks, called
  `gemma-python`, returned a cited answer, and reported no hidden thinking or
  API error.

## Ollama Position

- Local Ollama service: 0.24.0, active systemd service.
- Installed baseline model: `gemma-python:latest`.
- Python dependency: `ollama==0.6.2` in `uv.lock`.
- Stable baseline: keep `ETHNOS_OLLAMA_THINK=false`, `num_ctx=8192`, and
  `ETHNOS_OLLAMA_NUM_THREAD` unset.
- Compatibility option: `ETHNOS_OLLAMA_THINK=auto` omits the request field;
  `true`, `low`, `medium`, and `high` are accepted for controlled experiments
  with newer thinking models.
- Model policy: `gemma-python` is the review baseline and is currently a
  Gemma 4 based local alias. Gemma 3 profile names remain as compatibility
  scaffolding in the CLI, but new model work should evaluate Gemma 4 candidates
  or explicit hybrid/cloud profiles by benchmark.
- Upgrade policy: treat release candidates, nightly builds, and architecture
  rewrites as experimental until they beat the current benchmark without
  accuracy or validity regressions.
- Upstream references checked on 2026-06-01:
  [Ollama releases](https://github.com/ollama/ollama/releases),
  [Ollama REST API](https://github.com/ollama/ollama/blob/main/docs/api.md),
  [ollama-python v0.6.2](https://github.com/ollama/ollama-python/releases/tag/v0.6.2),
  [structured outputs](https://docs.ollama.com/capabilities/structured-outputs),
  [tool calling](https://docs.ollama.com/capabilities/tool-calling),
  [thinking](https://docs.ollama.com/capabilities/thinking),
  [vision](https://docs.ollama.com/capabilities/vision),
  [web search](https://docs.ollama.com/capabilities/web-search), and
  [Gemma 4 on Ollama](https://ollama.com/library/gemma4) /
  [Google Gemma docs](https://ai.google.dev/gemma/docs).

## Remaining Review Targets

- Keep section presets aligned with source PDFs before any future re-chunking or
  source-document replacement.
- Keep future changes inside the focused modules instead of expanding the public
  facades.
- Treat the local Canvas quiz source as derived from the PDF-backed quiz export:
  if an item is missing from the export, mark it unresolved instead of adding
  undocumented outside knowledge.
