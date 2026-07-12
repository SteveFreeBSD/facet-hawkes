# Performance Tuning

This guide is the shared tuning playbook for `ethnos`. Hardware-specific facts
belong in [`docs/hosts/`](hosts/README.md); project defaults belong here only
when they are safe across the current hosts.
Operational failures belong in
[`OLLAMA_TROUBLESHOOTING.md`](OLLAMA_TROUBLESHOOTING.md).

## Quick Defaults

- Use `gemma-python` as the working model.
- Keep `ETHNOS_OLLAMA_NUM_CTX=8192`.
- Keep `ETHNOS_OLLAMA_NUM_THREAD` unset for normal use.
- Keep `ETHNOS_OLLAMA_THINK=false`.
- Use `mc-bench --chars 300` for MC-only timing and comparison runs.
- Use `quiz-bench --chars 900` for mixed quizzes so essay drafts have more
  source context.
- Use repeated `quiz-bench --item-id ID` arguments for follow-up runs instead
  of repeating a complete CPU benchmark. The default single consistency retry
  applies only to responses that fail validation or evidence/selection checks;
  use `--answer-retries 0` for a strict one-call baseline.
- Keep the Ollama service override small: flash attention, mlock, and memlock
  infinity. Add keep-alive on hosts where repeated local runs benefit from it.
- On `caspian`, keep the host-level scheduler profile at `scx_bpfland` Auto
  through `scx_loader.service`; CPU governors remain `schedutil`.

These values reflect the measured `caspian` benchmark and still fit the faster
local `erosion` host. Re-test before changing defaults globally.

## Application Environment

Copy [`.env.example`](../.env.example) to `.env` only when local overrides are
needed. The app already has these defaults in code:

```bash
ETHNOS_DB_PATH=data/ethnos.sqlite
ETHNOS_OLLAMA_HOST=http://localhost:11434
ETHNOS_OLLAMA_MODEL=gemma-python
ETHNOS_OLLAMA_TIMEOUT=300
ETHNOS_OLLAMA_STRUCTURE_NUM_PREDICT=2048
ETHNOS_OLLAMA_ANSWER_NUM_PREDICT=1536
ETHNOS_OLLAMA_NUM_CTX=8192
ETHNOS_OLLAMA_THINK=false
ETHNOS_OLLAMA_NUM_THREAD=
```

`ETHNOS_OLLAMA_NUM_THREAD` is intentionally blank. Ollama's default scheduler
was much faster than fixed `4` or `6` thread settings in the measured MC
benchmark on `caspian`, including the 2026-07-11 retest on Ollama 0.31.1.

`ETHNOS_OLLAMA_THINK=false` is the tuned default for the current local Gemma
alias. Use `auto` to omit the `think` field entirely, or `true`, `low`,
`medium`, or `high` only in controlled model/version tests. Ollama supports a
`think` request field for thinking-capable models, while some model families
also document model-specific thinking controls; benchmark before adopting any
thinking mode as a project default.

## Ollama Service Override

The common systemd drop-in path is:

```text
/etc/systemd/system/ollama.service.d/override.conf
```

Recommended benchmark profile:

```ini
[Service]
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_MLOCK=1"
Environment="OLLAMA_KEEP_ALIVE=24h"
LimitMEMLOCK=infinity
```

`OLLAMA_KEEP_ALIVE=24h` keeps the model resident for repeated benchmark and
work sessions. On a 64 GiB host with one 7.2 GB model, this leaves >50 GiB
free for page cache, desktop apps, and the OS. For a dedicated benchmark day,
use `-1` (indefinite) instead. For a shared or resource-constrained host,
`30m` is still reasonable.

Apply and inspect:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
systemctl show ollama -p Environment -p LimitMEMLOCK -p ActiveState -p SubState
ollama --version
ollama list
```

Do not add per-request `use_mlock`; the installed Ollama build rejected that
option during earlier testing.

## Model Policy

The repo's default model name is `gemma-python`. For clean migrations and
repeatable benchmark comparisons, install only the model names the host needs.

`caspian` is intentionally lean and currently has only:

```text
gemma-python:latest
```

`erosion` has extra experimental local models, but they are not required for the
repo baseline and should not be treated as dependencies.

The current `gemma-python` alias is Gemma 4 based. It remains the source of
truth because it is the measured CPU-local model, not because it is the largest
or newest model available. New Gemma 4 variants should be evaluated as
benchmarked candidates, not silently substituted into review runs.

## Benchmark Protocol

Use one fixed quiz, change one variable, and save each report under
`data/runs/` so it stays out of git.

Create the current fixed MC quiz:

```bash
uv run ethnos generate-quiz 1 \
  --source terms \
  --difficulty medium \
  --limit 20 \
  --seed 42 \
  --output data/runs/perf-quiz-medium-20-current.json
```

Run the current MC baseline:

```bash
uv run ethnos mc-bench 1 \
  --quiz data/runs/perf-quiz-medium-20-current.json \
  --chars 300 \
  --num-ctx 8192 \
  --output data/runs/perf-current-mc.json
```

Run mixed quiz benchmarks separately:

```bash
uv run ethnos quiz-bench 1 \
  --quiz data/runs/perf-quiz-medium-20-current.json \
  --output data/runs/perf-current-mixed.json
```

Compare MC-only reports:

```bash
uv run ethnos mc-compare \
  data/runs/perf-baseline-mc.json \
  data/runs/perf-candidate-mc.json \
  --output data/runs/perf-compare-mc.json
```

Watch elapsed seconds, average answer seconds, accuracy, no-context count,
invalid-response count, selected chunks, retrieval queries, and whether the
model was already resident in `ollama ps`. A review-ready MC report should show
100% accuracy, zero no-context cases, and zero invalid responses on the current
seeded quiz.

## Current MC Source Of Truth

The current source-of-truth MC benchmark uses the seeded quiz generated by the
current `medium` distractor filter, `mc-bench --chars 300`, `num_ctx=8192`,
`ETHNOS_OLLAMA_NUM_THREAD` unset, and `gemma-python` on
[`caspian`](hosts/caspian.md).

The generator intentionally skips broad single-word source terms when a more
specific sibling term is present in the same chunk. That keeps benchmark
questions focused on answerability instead of ambiguous term boundaries such as
general concepts versus their named variants.

Keep `mc-bench --chars 300`, keep `num_ctx=8192`, and leave
`ETHNOS_OLLAMA_NUM_THREAD` unset for review runs. Use historical reports in
`data/runs/` only as local scratch data; they are ignored by git and are not the
project source of truth.

## SQLite Settings

`ethnos.db.connect()` applies:

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -32000;
PRAGMA temp_store = MEMORY;
PRAGMA mmap_size = 134217728;
```

For the current small database, SQLite is not the bottleneck. Revisit cache and
memory-map settings only when databases grow into hundreds of MiB or profiling
shows SQLite time dominating Ollama time.

## What Not To Tune Blindly

- Ollama thread count: use `ETHNOS_OLLAMA_NUM_THREAD` only for controlled A/B
  tests.
- Kernel VM knobs: avoid swappiness, dirty-ratio, transparent huge page, and
  scheduler changes unless monitoring points there.
- SQLite durability: keep WAL and `synchronous=NORMAL`; avoid
  `synchronous=OFF` for normal use.
- Larger context windows: raise `num_ctx` only when retrieval traces prove
  needed context is being truncated.
- Extra models: do not install them on the migration host unless a benchmark or
  workflow explicitly requires them.

## Optimization Plan (CachyOS + Ollama)

This plan is the comprehensive, reviewable checklist for improving throughput
on the CachyOS host while preserving answer quality. Treat the current repo
baseline as the reference and change one variable at a time with A/B benchmarks.

### Phase 0: Inventory (once per host)

Capture the current state before any changes and record it in
`docs/hosts/caspian.md`:

- Ollama version and installed models (`ollama --version`, `ollama list`).
- Service override settings (`systemctl show ollama -p Environment -p LimitMEMLOCK`).
- Active model residency (`ollama ps`).
- Kernel variant and CPU governor (CachyOS kernel flavor, scheduler notes).
- Memory pressure (swap/zram usage, sustained swap activity).

### Phase 0b: System Profile (once per host)

Apply a reversible sysctl for free-page reserve:

```text
# /etc/sysctl.d/99-ethnos-caspian.conf
vm.min_free_kbytes = 262144
```

This raises the kernel's free-page reserve from the default (~90 MB on 64 GiB)
to 256 MB (~0.4% of RAM). It gives the kernel more headroom for atomic
allocations while Ollama mlocks a 7.2 GB model. Apply with
`sudo sysctl --system` and verify with `sysctl vm.min_free_kbytes`.

Rollback: `sudo rm /etc/sysctl.d/99-ethnos-caspian.conf && sudo sysctl --system`.

### Phase 1: Baseline (lock a reference)

- Confirm the model is warm (`ollama ps` shows `gemma-python:latest` loaded).
- Close browser, editor, and video work for a clean CPU test.
- Run `mc-bench --chars 300` and `quiz-bench --chars 900` using the current
  defaults.
- Save reports under `data/runs/` and note elapsed seconds, average answer
  seconds, accuracy, and no-context count.
- This warm-model, default-scheduler baseline is the reference every subsequent
  test must beat.

2026-07-11 note: on `caspian`, the first warm run was a poor timing reference
because the later hot-control run was an order of magnitude faster. Use the
hot-control run as the scheduler comparison baseline:
`data/runs/perf-caspian-schedutil-hot-control-20260711-mc.json`.

### Phase 2: Ollama Upgrade Evaluation

- As of 2026-07-11, `caspian` is on Ollama 0.31.1. The last recorded
  `erosion` snapshot is 0.24.0 and must be rechecked on-host before comparison.
  The tracked Python client remains `ollama==0.6.2` in `uv.lock`.
- Treat release candidates, nightly builds, and architecture rewrites as
  experimental until they prove faster and stable under the same benchmarks.
- Do not replace the current install in place. Prefer a side-by-side run or
  temporary binary test, then compare results against the baseline.
- Gate adoption on equal-or-better accuracy and reduced elapsed time.

### Phase 3: Runtime Knobs (A/B only)

Test one variable at a time, revert if accuracy regresses:

- `ETHNOS_OLLAMA_NUM_CTX`: only increase if retrieval traces show truncation.
- `ETHNOS_OLLAMA_STRUCTURE_NUM_PREDICT` and `ETHNOS_OLLAMA_ANSWER_NUM_PREDICT`:
  reduce if responses remain valid and accuracy is unchanged.
- `ETHNOS_OLLAMA_NUM_THREAD`: re-test on each Ollama version because scheduler
  behavior can change between releases.
- Keep `ETHNOS_OLLAMA_THINK=false` unless quality requirements change.

### Phase 4: Service-Level Optimizations

Verify the baseline service override remains effective:

- `OLLAMA_FLASH_ATTENTION=1`
- `OLLAMA_MLOCK=1`
- `LimitMEMLOCK=infinity`
- `OLLAMA_KEEP_ALIVE=24h` on hosts running repeated local benchmarks (or `-1`
  for dedicated benchmark days)

Confirm there are no mlock warnings and that model reloads are minimized.

### Phase 5: CachyOS OS-Level Experiments (guarded)

Only attempt these if profiling shows CPU scheduling or kernel behavior as the
bottleneck:

- Validate the kernel flavor (CachyOS default vs. `linux-cachyos-bore`) and
  measure impact with identical benchmarks.
- Consider sched-ext or BORE only with before/after measurements and a clear
  rollback path.
- Do not adjust swappiness, THP, or other VM knobs without data showing memory
  pressure or paging as the limiting factor.

2026-07-11 `caspian` result: `scx_bpfland` Auto was selected and made
boot-persistent with `/etc/scx_loader.toml`:

```toml
default_sched = "scx_bpfland"
default_mode = "Auto"
```

`scx_loader.service` is enabled. The winning MC reports were:

- `data/runs/perf-caspian-bpfland-auto-warm-20260711-mc.json`
- `data/runs/perf-caspian-bpfland-auto-repeat-20260711-mc.json`

The direct `performance` governor, `scx_lavd` Gaming, `scx_flash` LowLatency,
and fixed `ETHNOS_OLLAMA_NUM_THREAD=4/6` did not beat the winning profile.
Mixed validation on the winning profile is recorded in
`data/runs/perf-caspian-bpfland-mixed-warm-20260711.json`.

### Phase 6: Selection and Roll-In

- Choose the fastest configuration that preserves accuracy.
- Update `.env.example`, `docs/PERFORMANCE_TUNING.md`, and
  `docs/CURRENT_BASELINE.md` to reflect the chosen defaults.
- Re-run the baseline smokes and verify no regressions.

### Success Criteria

- Accuracy unchanged vs. baseline for MC and mixed quizzes.
- Elapsed time and average answer seconds improved.
- No new failures, invalid responses, or Ollama timeouts.
- Clear documentation of changes and rollback steps.

### Code-Level Micro-Optimizations (Audit)

These are low-risk candidates found during code review. Apply only after
benchmarking because some changes trade CPU work for fewer I/O calls.

- Applied: cache prompt templates to avoid disk reads in hot paths:
  - `ethnos.qa.build_answer_prompt()` reads [prompts/answer.md](../prompts/answer.md)
    on every call.
  - `ethnos.ollama_client.load_prompt()` reads prompt files per extraction call.
  - `ethnos.quiz` MC, choice, and essay prompt builders read prompt files during
    quiz benchmarks.
  - Implementation: prompt-template loaders now use small `lru_cache` instances.
- Applied: cache schema generation and compaction:
  - `ExtractionResult.model_json_schema()` and `_compact_json_schema()` run on
    every structured extraction call in `extract_chunk()`.
  - Implementation: structured extraction schema generation is memoized.
- Applied: optionally return chunk text directly from the FTS query:
  - `context_chunks()` calls `search_chunks()` and then a second SQL query to
    fetch `text` by id.
  - Implementation: `search_chunks(..., include_text=True)` selects `c.text`;
    `context_chunks()` uses that path while the default search result shape
    stays unchanged.
- Pre-compile comparison regex patterns in [src/ethnos/qa.py](../src/ethnos/qa.py)
  to avoid recompiling on each comparison detection pass.

Document any applied change and re-run the MC + mixed benchmarks before
declaring a new baseline.

## Getting More From gemma-python

These recommendations target answer quality and reliability without switching
to a larger or slower model. They are ordered by expected impact. Bug fixes
referenced here are documented in [`CODE_REVIEW.md`](CODE_REVIEW.md). Treat the
items below as benchmark candidates; adopt them only after they preserve
accuracy, validity, and review trace quality.

Upstream references checked on 2026-06-27:

- [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs)
  support JSON schema/Pydantic validation through the `format` field.
- [Ollama tool calling](https://docs.ollama.com/capabilities/tool-calling)
  supports multi-turn agent loops with tool results fed back into chat history.
- [Ollama vision](https://docs.ollama.com/capabilities/vision) models accept
  images alongside text, and structured outputs can be combined with vision.
- [Ollama web search/fetch](https://docs.ollama.com/capabilities/web-search)
  exists as an explicit cloud/API-backed capability.
- [Gemma 4 on Ollama](https://ollama.com/library/gemma4) and
  [Google's Gemma docs](https://ai.google.dev/gemma/docs) now present Gemma 4
  as the current Gemma family, with edge-sized E2B/E4B variants, long context,
  multimodal inputs, and model-specific thinking notes.

### Expand deterministic pre-processing

The strongest leverage with a small model is doing reasoning before the prompt.
The existing `_negative_option_guidance`, `_both_option_guidance`, and
`_percentage_complement_guidance` helpers in
[`quiz_prompts.py`](../src/ethnos/quiz_prompts.py) already do this well.
Candidates for expansion:

- **Chronological questions**: Detect date patterns (`\b\d{4}\b`) in retrieved
  context and inject ordering guidance. Pure string matching, no model needed.
- **Definition-matching questions**: Compute token-overlap scores between each
  option text and the retrieved context near the target, then inject hit counts
  as guidance. Extends the existing `_option_text_supported` pattern.
- **Enumeration/list questions**: Pre-scan retrieved context for each option's
  text and inject hit/miss counts when the question asks "which of the
  following."

### Reduce the format tax on complex schemas

Grammar-constrained decoding on small models can trade reasoning quality for
structural validity. The MC schema (`{"selected_option": "A"}`) is lightweight.
The choice and essay schemas are heavier (3 and 5 required fields).

For accuracy benchmarks, consider a two-stage approach:

1. Use the simple MC schema to get the answer with minimal format overhead.
2. Only request evidence/citations in a follow-up constrained call when needed.

This applies mainly to `mc-bench` where evidence is not scored. `quiz-bench`
already needs the full choice response shape.

### Context budget refinements

Current defaults are `--chars 300` for MC bench and `--chars 900` for mixed.

- **Sentence-boundary clipping**: `_targeted_context_text` clips at character
  offsets. Adjusting the window start/end to the nearest sentence boundary
  (`. ` or `\n`) gives the model cleaner input at the same character budget.
- **Context deduplication**: Multiple retrieved chunks may contain overlapping
  text from chunking overlap. A lightweight dedupe pass (skip a chunk if most
  of its significant terms already appear in selected chunks) improves
  information density per context character.

### Error-aware retries

The current `_repair_prompt` appends a generic "your previous response was not
valid JSON" message. With grammar-based sampling, JSON syntax errors are rare.
The more likely failures are Pydantic `ValidationError` (correct JSON, wrong
content).

Making the repair prompt aware of the specific validation error tells the model
what to fix:

```python
def _repair_prompt(original_prompt, validation_error=None):
    if validation_error:
        return (
            original_prompt
            + f"\n\nYour response had valid JSON but failed validation: "
            + f"{validation_error}\nFix the specific issue."
        )
    return original_prompt + "\n\nReturn ONLY valid JSON matching the schema."
```

### Agent deterministic fallback improvements

The deterministic fallback already scores 17/20 pass on the History chapter 20
fixture with zero LLM calls. Two extensions:

- **Key-terms cross-reference**: If the keyed answer text matches a
  `key_terms` record in the database, use it as evidence directly. A SQL lookup
  is faster and more reliable than an FTS search.
- **Distractor plausibility scoring**: Check whether distractor terms appear
  anywhere in the document (not just retrieved chunks). A distractor present in
  a different chapter is `plausible_but_wrong`; one absent everywhere is
  `not_discussed`.

### num_predict right-sizing

For MC questions with the simple `{"selected_option": "A"}` schema, the
response is usually 20-30 characters. The default 768 tokens (`cpu-local`) is
generous. Testing `num_predict=128` for MC-only runs is reasonable, but adopt it
only if the benchmark keeps accuracy, invalid-response count, and no-context
count unchanged.

### Pre-compile comparison regex patterns

The 12 regex patterns in `qa.py` `extract_comparison_subqueries` are
recompiled on every call. Pre-compiling them as module-level constants is a
free improvement. Already noted in the Code-Level Micro-Optimizations section
above.

## Host Profiles

- [`erosion`](hosts/erosion.md): local development host, Ryzen 7 PRO 5850U,
  Zen kernel, multiple local Ollama models.
- [`caspian`](hosts/caspian.md): migrated host, Ryzen Embedded V1756B,
  CachyOS, only `gemma-python`, measured MC tuning source.
