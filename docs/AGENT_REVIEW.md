# Agent Review

Agent Review is the model-driven review layer for Ethnos. It lets a local or
hybrid Ollama model inspect quiz items with deterministic Ethnos tools, cite
PDF evidence, flag answer-key risks, and write a CTO-ready report.

The local path does not depend on the model to do all the work. Each item
gets deterministic preflight grounding first, using the question, keyed answer,
question-plus-key, retrieval hints, target, and option text. This keeps the
review useful when a small local model calls tools imperfectly or fails to
produce a final structured verdict.

Grounding is keyed-answer aware: rows that support the keyed answer are ranked
above broad question-only matches, PDF line-break hyphenation is normalized, and
answer terms are canonicalized for simple spelling/plural variants before a
fallback verdict is accepted.

The review layer also scores the evidence behind each fallback verdict. Every
item receives `evidence_strength`, `confidence_score`, `support_reason`,
`review_priority`, and per-option `distractor_verdicts`. This makes the report a
review queue, not just a list of answers: clean items can pass, while typo,
duplicate, ambiguous, weakly grounded, or source-missing items stay visible for
human inspection.

## Command

```bash
uv run ethnos agent-review 2 \
  --quiz benchmarks/history_ch20_canvas.json \
  --output data/runs/history_ch20_agent_review \
  --model gemma-python \
  --profile cpu-local
```

Useful options:

- `--allow-web`: enable Ollama web search/fetch tools for explicitly hybrid
  review runs.
- `--vision-pages auto|off|on`: allow rendered PDF page images to be inspected
  by a vision-capable model such as Gemma 4.
- `--max-steps 8`: cap the structured tool loop for each quiz item.
- `--item-timeout 120`: cap total wall time for one quiz item before falling
  back to deterministic review. `0` disables the cap.
- `--debug-agent`: write `tool_trace.jsonl` beside the reports.
- `--model-profile cpu-local|review-local|gemma3-local|gemma3-fast|hybrid-max`:
  choose the model profile and context/output defaults.
- `--profile cto`: convenience alias for the review-ready `review-local`
  profile.

## Outputs

The output directory contains:

- `agent_review.md`: human-readable review.
- `agent_review.json`: structured report with verdicts, evidence, and question
  quality findings, evidence strength, confidence, review priority, and
  distractor audit fields.
- `tool_trace.jsonl`: optional model action and tool result trace.

Each run is also persisted to SQLite in `agent_runs` and `agent_findings`.

## Model Profiles

- `cpu-local`: compatibility name for the smallest local review budget with
  `gemma-python`.
- `review-local`: slightly larger local review budget with `gemma-python`.
- `gemma3-local`: optional 12B-class Gemma 3 profile for explicit model
  comparisons; it is not a baseline fallback.
- `gemma3-fast`: optional smaller Gemma 3 comparison profile.
- `hybrid-max`: max-capability profile for explicit web/cloud-assisted review.

Existing `gemma-python` workflows remain the local baseline for structure
extraction, Q&A, quiz benchmarking, and Agent Review. The profile name
`cpu-local` predates Vulkan enablement; on `caspian`, Ollama offloads Gemma to
the Vega GPU. New model profiles must beat the same quality and stability gates
before changing defaults.

## Review Meaning

Verdicts:

- `key_supported`: the keyed answer is supported by available evidence.
- `key_conflict_candidate`: source-backed review suggests another answer.
- `source_missing`: local PDF evidence is missing or unavailable.
- `ambiguous_question`: wording/options are not precise enough.
- `needs_human_review`: the agent could not safely finalize the item.

Quality findings are separate from verdicts. For example, History chapter 20
flags the repeated New Freedom prompt and the `Temperence` spelling while still
preserving the keyed answers.

Evidence strength values:

- `direct`: the retrieved evidence contains the canonical answer phrase.
- `strong`: the evidence contains all significant keyed-answer terms.
- `partial`: enough significant terms are present to support the answer, but the
  source wording is conceptual rather than exact.
- `weak`: only a small amount of answer language appears in evidence.
- `missing`: the retrieval set does not materially support the answer.

Review priorities:

- `pass`: supported answer with no quality note requiring inspection.
- `inspect`: supported or unresolved item with a quality note, conceptual
  evidence, weak evidence, or model-finalization gap.
- `fix`: source-missing, conflict-candidate, or ambiguous item that should block
  release until corrected or explicitly accepted.

The current local history chapter 20 probe reports `20` supported keyed
answers, `17` pass items, and `3` inspect items: the two duplicate New Freedom
prompts and the `Temperence` spelling note.

A compact checked-in example is available at
[`examples/history_ch20_agent_review_summary.md`](../examples/history_ch20_agent_review_summary.md).

For the fastest local review with deterministic fallback, prefer:

```bash
uv run ethnos agent-review 2 \
  --quiz benchmarks/history_ch20_canvas.json \
  --output data/runs/history_ch20_agent_review_local \
  --model gemma-python \
  --profile cto \
  --vision-pages off \
  --max-steps 1 \
  --debug-agent
```
