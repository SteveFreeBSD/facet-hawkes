# Performance Tuning

This document records the current measured decisions and the protocol for
changing them. Machine facts belong in [hosts/caspian.md](hosts/caspian.md),
and the accepted result belongs in [CURRENT_BASELINE.md](CURRENT_BASELINE.md).

## Current decisions

| Area | Selected value | Reason |
|---|---|---|
| Model | `gemma-python` | Best fit for the Ethnos workload on this host |
| Acceleration | Ollama Vulkan/RADV | All 36 Gemma layers offload; `ollama ps` reports 100% GPU |
| Context | `4096` | Faster and more accurate than the tested 8K run |
| Prompt batch | Ollama/model default `512` | Faster on Ethnos's short prompts than the 256 candidate |
| Thinking | `false` | Avoids hidden-token budget and empty visible responses |
| CPU threads | unset | Fixed thread counts were previously much slower |
| MC excerpt | `--chars 300` | Fastest accepted MC context size |
| Mixed excerpt | `--chars 900` | Retains broader evidence for essays and mixed items |
| Scheduler | kernel default | sched-ext is disabled; obsolete CPU-only scheduler results are not guidance |
| Keepalive | `24h` | Avoids repeated Gemma cold loads during work sessions |

Do not change more than one performance variable in a benchmark candidate.
Accuracy, response validity, stability, and reproducibility take precedence over
tokens per second.

## Application defaults

The authoritative defaults table is in
[CURRENT_BASELINE.md](CURRENT_BASELINE.md#supported-configuration) and the
implementation is in `src/ethnos/config.py`. Performance-sensitive invariants
are context `4096`, `think=false`, and no fixed thread count.

Leave `ETHNOS_OLLAMA_NUM_THREAD` blank unless a controlled benchmark on the
current Ollama version proves otherwise.

## Ollama service profile

The exact accepted drop-in, path, application commands, and persistence notes
live in [hosts/caspian.md](hosts/caspian.md#vulkan-and-ollama). Benchmarking
depends on flash attention, iGPU enablement, mlock, unlimited memlock, and the
24-hour keepalive remaining active.

`OLLAMA_IGPU_ENABLE=1` is required for the tested Vega Vulkan path. Do not add
undocumented request options or global KV-cache quantization without an A/B
test; service-wide options affect every model.

## Benchmark protocol

Use the fixed local fixture:

```text
data/runs/perf-quiz-medium-20-current.json
```

If it must be regenerated:

```bash
uv run ethnos generate-quiz 1 \
  --source terms \
  --difficulty medium \
  --limit 20 \
  --seed 42 \
  --output data/runs/perf-quiz-medium-20-current.json
```

Cold acceptance run:

```bash
ollama stop gemma-python
uv run ethnos mc-bench 1 \
  --quiz data/runs/perf-quiz-medium-20-current.json \
  --chars 300 \
  --model gemma-python \
  --num-ctx 4096 \
  --num-predict 64 \
  --output data/runs/gemma-candidate-cold.json
```

Record whether the runner was cold or warm. Do not compare a cached run against
a cold run: Ollama can reuse prompt cache across aliases that share weights.
Stop the model between candidates when comparing model parameters.

Compare reports with:

```bash
uv run ethnos mc-compare \
  data/runs/gemma-baseline.json \
  data/runs/gemma-candidate.json \
  --output data/runs/gemma-compare.json
```

Acceptance requirements:

- 20/20 on the fixed MC quiz
- Zero invalid responses
- Zero no-context cases
- No Ollama or AMDGPU resets
- Lower elapsed time under the same cold/warm condition
- No regression in focused workflow tests

## Measured Gemma results

All full runs used the same 20-item fixture, `--chars 300`, no fixed CPU thread
count, and a cold runner.

| Candidate | Accuracy | Invalid | Elapsed |
|---|---:|---:|---:|
| Gemma, 8K context | 19/20 | 0 | 189.3 s |
| Gemma, 4K before retrieval fix | 19/20 | 0 | 120.9 s |
| Gemma, 4K, batch-256 candidate alias | 20/20 | 0 | 124.5 s |
| **Gemma, 4K, default batch 512, retrieval fix** | **20/20** | **0** | **118.1 s** |

The accepted 4K configuration is 71.2 seconds (37.6%) faster than the tested
8K run.

### Prompt batch result

A sustained 2,678-token synthetic prompt favored smaller batches:

| Batch | Prompt throughput | Generation throughput | Total including load |
|---:|---:|---:|---:|
| 128 | 127.8 tok/s | 11.40 tok/s | 35.6 s |
| 256 | 130.0 tok/s | 11.51 tok/s | 35.3 s |
| 512 | 109.2 tok/s | 11.40 tok/s | 39.1 s |
| 1024 | 72.9 tok/s | 11.46 tok/s | 51.2 s |

Ethnos's real MC prompts are shorter. On the full workload, batch 512 beat the
batch-256 alias by 6.4 seconds. The application therefore retains the model's
512 default. The synthetic result remains useful only for future long-prompt
workloads.

### Retrieval optimization

Question `q0005` asks for “normative ethics,” but the source chunk does not
contain that exact phrase. It contains an early direct definition and a later
metaethics passage with the same target tokens. The old tie-breaker preferred
the later occurrence, feeding Gemma the wrong 300-character excerpt.

The accepted implementation ranks approximate windows by:

1. Number of target tokens present.
2. Smallest span between those tokens.
3. Most specific matched token.
4. Earliest equally good occurrence.

That deterministic fix changed `q0005` from D to the supported answer B and is
covered by a regression test. It is a larger quality improvement than any model
or kernel experiment in the current round.

## Qwen experiment

`qwen3-coder:30b` is a Q4_K_M mixture-of-experts model with approximately 3.3B
active parameters and an 18 GB weight blob. Ollama successfully offloaded all
49 layers through Vulkan.

Measured observations:

- Short 4K generation: about 9.9 tok/s warm.
- 16K generation: about 8.3 tok/s.
- Realistic code response: about 8.4 tok/s.
- Sustained 8K prompts triggered Vega compute-ring resets in two configurations;
  one batch-512 run completed but did not establish reliable 8K operation.
- Prompt-only specialization did not make one-pass systems code reliably satisfy
  all failure-path requirements.

Decision: Qwen is optional and parked. It is not an Ethnos dependency, fallback,
or performance baseline. The tags may remain installed because they share one
weight blob and consume no GPU/RAM while unloaded. Remove all Qwen tags together
only when reclaiming approximately 18 GB of disk.

## Do not retune blindly

- Do not raise context without a trace showing required evidence was truncated.
- Do not pin CPU threads without a current-version A/B test.
- Do not re-enable sched-ext based on the obsolete CPU-only benchmark ladder.
- Do not change swappiness, THP, dirty ratios, clocksource, or GPU timeout values
  without a reproduced bottleneck and rollback plan.
- Do not increase output budgets when `done_reason` is already `stop`.
- Do not judge prompt processing with repeated identical prompts unless the
  prompt cache is intentionally part of the test.
- Do not promote a faster result that loses accuracy or produces GPU resets.

SQLite is not a current bottleneck. The database uses WAL,
`synchronous=NORMAL`, a 32 MiB cache, memory temp storage, and a 128 MiB mmap;
revisit those values only when profiling shows database time dominating model
time.

## Promoting a future winner

1. Save the baseline report.
2. Change one variable.
3. Clear the runner when a cold comparison is required.
4. Run focused tests, then the complete acceptance benchmark.
5. Confirm temperatures, swap, `ollama ps`, and kernel logs.
6. Update `src/ethnos/config.py`, `.env.example`,
   `CURRENT_BASELINE.md`, and the relevant host profile together.
7. Keep an explicit rollback command or previous model tag.
