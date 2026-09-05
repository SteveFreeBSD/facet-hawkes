# Current Baseline

> **Superseded.** This records the baseline measured on the HP t740 named
> `caspian`, against a model alias that exists only on that machine. Every
> figure below was measured there and none of it describes the current host
> `casbox` or its models — see the README's *Current supported baseline*.
> Nothing here is reattributed to a different model, because a measurement
> belongs to the thing that produced it.

Last verified on `caspian`: 2026-07-19.

The screenshot OCR/exact-math stack is a staged candidate as of 2026-09-02;
it does not replace the accepted general-purpose baseline below until its
acceptance gate passes. See
[Vision and Exact-Math Architecture](VISION_MATH_ARCHITECTURE.md).

This is the single source of truth for the known-good Ethnos application,
runtime data, model, and acceptance benchmark. Hardware and persistent service
details live in [hosts/caspian.md](hosts/caspian.md). Reproduction steps live in
[MIGRATION.md](MIGRATION.md).

## Supported configuration

| Setting | Current value |
|---|---|
| Default model | `gemma-python` |
| Ollama endpoint | `http://localhost:11434` |
| Context | `4096` |
| Structure output budget | `2048` |
| Answer output budget | `1536` |
| Thinking | `false` |
| Candidate primary screenshot OCR | `qwen3.5:4b` |
| Candidate screenshot verifier | `gemma-python` |
| Candidate vision output budget | `256` per pass |
| Candidate image-question fallback solver | `qwen3.5:4b` |
| Ollama thread override | unset |
| MC context excerpt | `--chars 300` |
| Mixed-quiz context excerpt | `--chars 900` |

The defaults are implemented in `src/ethnos/config.py` and mirrored in
`.env.example`. Ethnos does not automatically load `.env`; use
`uv run --env-file .env ethnos ...` when overrides are needed.

The `gemma-python` Modelfile also uses a 4096-token context, a 500-token default
output cap, temperature `0.2`, `top_k=64`, and `top_p=0.95`. Ethnos requests
override temperature, context, and output budgets where appropriate; MC
benchmark requests use temperature `0`.

## Primary host

`caspian` is an HP t740 with a Ryzen Embedded V1756B, 64 GiB RAM, and integrated
Vega 8 graphics. The active stack is:

- CachyOS kernel `7.1.3-2-cachyos`.
- BIOS `M42 v01.23` dated 2026-04-27.
- Ollama `0.32.1`.
- Mesa/RADV Vulkan on the Vega iGPU.
- Ollama service: flash attention, iGPU enablement, mlock, 24-hour keepalive,
  and unlimited memlock.
- Kernel sched-ext disabled; the kernel default scheduler is in use.
- CPU governor `schedutil`, power profile `balanced`, clocksource `hpet`.
- 61.7 GiB zram swap, with zero use during the final validation.

`ollama ps` reports `gemma-python` at `100% GPU`, context `4096`, and an active
runner allocation of about 1.8 GB. Ollama logs confirm all 36 layers are
offloaded. Because this is an integrated GPU, Vulkan memory is backed by shared
system RAM even though Ollama labels the runner as GPU-resident.

Qwen 3 Coder remains installed as an optional experiment but is not loaded and
is not required by Ethnos. Its three tags share one approximately 18 GB weight
blob. It must not be treated as a fallback or baseline dependency.

## Acceptance benchmark

Fixture:

```text
data/runs/perf-quiz-medium-20-current.json
```

Command:

```bash
ollama stop gemma-python
uv run ethnos mc-bench 1 \
  --quiz data/runs/perf-quiz-medium-20-current.json \
  --chars 300 \
  --model gemma-python \
  --num-ctx 4096 \
  --num-predict 64 \
  --output data/runs/gemma-current-cold.json
```

Current result:

| Metric | Result |
|---|---:|
| Correct | 20/20 |
| Accuracy | 100% |
| Invalid responses | 0 |
| No-context cases | 0 |
| Elapsed, including cold load | 118.1 seconds |

The preceding 8K candidate scored 19/20 in 189.3 seconds. The final 4K profile
is 71.2 seconds (37.6%) faster and more accurate on the fixed acceptance run.

The quality gain came from fixing approximate-target excerpt selection, not
from a larger model or longer context. When an exact target phrase is absent,
Ethnos now prefers the window where all target tokens occur closest together,
then the earliest equally good match. This corrected the `normative ethics`
item, whose source chunk also contains a later but irrelevant metaethics
passage. The behavior has a dedicated regression test.

See [PERFORMANCE_TUNING.md](PERFORMANCE_TUNING.md) for the full 4K/8K, batching,
and Qwen decision record.

## Chapter 27 Canvas acceptance

The Chapter 27 history fixture is a separate end-to-end functional acceptance
run; it does not replace the fixed performance benchmark above.

| Metric | Result |
|---|---:|
| Imported questions / points | 20 / 100 |
| Valid local PDF anchors | 19 |
| Explicit local source gaps | 1 |
| Grounded correct | 19/19 |
| Grounded accuracy | 100% |
| Instructor-key agreement on scored items | 19/19 |
| Source coverage | 19/20 (95%) |
| Key conflicts | 0 |
| Invalid responses / no-context cases | 0 / 0 |
| Answer retries | 0 |
| Elapsed model benchmark | 235.6 seconds |
| Deterministic Agent verdicts | 17 supported / 2 human-review / 1 source-missing |
| Agent priorities | 6 pass / 13 inspect / 1 fix |

The uncovered item asks about Warren Court protections for criminal
defendants, material that is absent from the local `history.pdf`. It remains an
explicit `external_source_item`; Ethnos skips it without querying unrelated
text. The two Agent human-review verdicts are items 15 and 16: conceptual
counterculture wording and a formal-war-declaration qualifier not stated in the
anchored passage. Four instructor-key notes are also explicit quality findings,
which keeps otherwise supported items 5 and 10 in the inspection queue. See the
[Chapter 27 findings](../examples/history_ch27_e2e_findings.md) for provenance,
wording notes, exact commands, and the supplied answer sequence.

## Runtime data

The ignored local database currently contains:

| Item | Count |
|---|---:|
| Documents | 2 |
| Pages | 582 |
| Chunks | 257 |
| Valid latest structured chunks | 257 |
| Chunk summaries | 257 |
| Topics | 465 |
| Key terms | 852 |
| Examples | 390 |
| Questions | 590 |
| Extraction runs | 28 |

Documents:

- Document `1`: `ethics.pdf`, 118 pages, 100 chunks, SHA prefix
  `eac21ab05849`.
- Document `2`: `history.pdf`, 464 pages, 157 chunks, SHA prefix
  `81ad69f0b520`.

Both documents have complete section labels and valid latest structured output
for every chunk. Admin/support material retains summaries, while normalized key
terms and questions remain focused on core content.

Local files that require separate backup or migration:

- `data/ethnos.sqlite` (about 12 MiB)
- `data/incoming/ethics.pdf` (about 1.9 MiB)
- `data/incoming/history.pdf` (about 6.9 MiB)
- Optional reports, traces, and exports under `data/runs/` and
  `data/processed/`

## Verification

Cheap checks that do not perform a long model run:

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run python -m compileall -q src tests
uv run vulture src tests --min-confidence 80
uv run ethnos documents
uv run ethnos db-info
uv run ethnos section-status 1
uv run ethnos structure-status 1
uv run ethnos section-status 2
uv run ethnos structure-status 2
uv run ethnos qa-bench 1 --benchmark benchmarks/ethics_qa.json --no-ask
```

Last staged deterministic verification on 2026-09-02: 284 tests passed, Ruff
passed, formatting passed, compilation passed, vulture passed, documentation
links passed, and `git diff --check` passed.

Model/Vulkan smoke:

```bash
uv run ethnos ask 1 "What is virtue ethics?" --limit 2 --debug-ollama
ollama ps
```

Expected: `gemma-python`, context `4096`, `100% GPU`, no hidden thinking, and no
API error.

## Expensive or mutating operations

Run these intentionally and write reports under `data/runs/`:

- `structure`, especially `--force` or `--all-roles`
- PDF ingestion, chunking, or relabeling
- Model-backed QA and quiz benchmarks
- Agent Review over many items
- Multi-model comparisons
- Database rebuilds

Start with one chunk or a small item subset. Back up `data/ethnos.sqlite` before
re-ingestion, rechunking, or a full structured rebuild. For recovery and host
migration, follow [MIGRATION.md](MIGRATION.md) rather than duplicating the steps
here.
