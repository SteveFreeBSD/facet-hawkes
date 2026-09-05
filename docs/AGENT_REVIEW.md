# Agent Review

Agent Review is the model-driven review layer for Ethnos. It lets a local or
hybrid Ollama model inspect quiz items with deterministic Ethnos tools, cite
PDF evidence, flag answer-key risks, and write a CTO-ready report.

The local path does not depend on the model to do all the work. Each item gets
deterministic preflight grounding first. Declared anchors are loaded directly;
unanchored items use the question, keyed answer, question-plus-key, retrieval
hints, target, and option text. This keeps the review useful when a small local
model calls tools imperfectly or fails to produce a final structured verdict.

Grounding is keyed-answer aware: rows that support the keyed answer are ranked
above broad question-only matches, PDF line-break hyphenation is normalized, and
answer terms are canonicalized for simple spelling/plural variants before a
fallback verdict is accepted.

Declared source anchors are authoritative and exclusive. Preflight loads every
declared chunk in manifest order without mixing in broad retrieval results.
Items tagged `external_source_item` or incomplete skip retrieval entirely and
cannot inherit incidental evidence from another part of the PDF.
Final citations come only from successful tool observations and, for anchored
items, only from the declared chunks. Keyed-answer/target-focused excerpts keep
support late in a long chunk visible without accepting model-authored citation
fields as provenance.

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
  --model qwen3.5:9b \
  --profile cpu-local
```

Useful options:

- `--allow-web`: enable Ollama web search/fetch tools for explicitly hybrid
  review runs.
- `--vision-pages auto|off|on`: allow rendered PDF page images to be inspected
  by a vision-capable model such as Gemma 4.
- `--max-steps 8`: cap the structured tool loop for each quiz item. Use `0`
  for an explicit deterministic preflight/fallback audit with no model call.
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

The report summary also distinguishes `model_finalized_count` from
`fallback_item_count`. A fresh debug run truncates its trace before writing, so
rerunning into the same output directory cannot silently duplicate old events.
Runtime action validation rejects a `final_review` attached to any tool other
than `finalize_item_review` and asks the model to correct the malformed action.
A repeated `ground_quiz_item` request is returned as a non-mutating error
because preflight already performed that work.

Each run is also persisted to SQLite in `agent_runs` and `agent_findings`.

## Model Profiles

- `cpu-local`: compatibility name for the smallest local review budget with
  `qwen3.5:9b`.
- `review-local`: slightly larger local review budget with `qwen3.5:9b`.
- `gemma3-local`: optional 12B-class Gemma 3 profile for explicit model
  comparisons; it is not a baseline fallback.
- `gemma3-fast`: optional smaller Gemma 3 comparison profile.
- `hybrid-max`: max-capability profile for explicit web/cloud-assisted review.

Existing `qwen3.5:9b` workflows remain the local baseline for structure
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
preserving the keyed answers. Nonempty `instructor_key_note` metadata is also a
quality finding, so editorial caveats remain visible in the review queue.

Evidence strength values:

- `direct`: the retrieved evidence contains the canonical answer phrase.
- `strong`: the evidence contains all significant keyed-answer terms.
- `partial`: enough significant terms are present to support the answer, but the
  source wording is conceptual rather than exact.
- `weak`: only a small amount of answer language appears in evidence.
- `missing`: the retrieval set does not materially support the answer.

Review priorities:

- `pass`: supported answer with no quality note requiring inspection.
- `inspect`: supported or unresolved item with a quality note, conceptual or
  weak evidence, or a model-finalization gap that deterministic evidence cannot
  resolve safely.
- `fix`: source-missing, conflict-candidate, or ambiguous item that should block
  release until corrected or explicitly accepted.

These are enforced report invariants, not merely model suggestions. Missing
local source always has `missing` evidence, confidence `0.0`, no citations, and
priority `fix`. Invalid or incomplete anchors cannot pass. Partial evidence,
quality findings, or a distractor explicitly classified as ambiguous force
`inspect`, even if a model proposes `pass`; direct/strong evidence below 0.75
confidence is also inspectable. Mere mention of a distractor in the same source
chunk is recorded as plausible, not automatically ambiguous. Acronyms require
exact matches, and negation qualifiers must bind to answer language, so
substrings or detached phrases do not create false support.

The current local history chapter 20 probe reports `20` supported keyed
answers, `17` pass items, and `3` inspect items: the two duplicate New Freedom
prompts and the `Temperence` spelling note.

A compact checked-in example is available at
[`examples/history_ch20_agent_review_summary.md`](../examples/history_ch20_agent_review_summary.md).
The complete Chapter 27 acceptance findings are recorded at
[`examples/history_ch27_e2e_findings.md`](../examples/history_ch27_e2e_findings.md).

The verified deterministic Chapter 27 review reports 17 `key_supported`, 2
`needs_human_review`, and 1 `source_missing` verdict. Its priority queue contains
6 pass, 13 inspect, and 1 fix items. Items 15 and 16 are deliberately not
rubber-stamped: the former is conceptually rather than lexically supported, and
the latter's “without a formal declaration of war” qualifier is not stated in
the anchored passage. Four instructor-key notes also remain visible as quality
findings. The `--max-steps 0` run records 0 model-finalized and 20 fallback
items by design.

For the fastest local review with deterministic fallback, prefer:

```bash
uv run ethnos agent-review 2 \
  --quiz benchmarks/history_ch27_canvas.json \
  --output data/runs/history_ch27/agent_review \
  --model qwen3.5:9b \
  --profile review-local \
  --vision-pages off \
  --max-steps 0 \
  --item-timeout 0 \
  --debug-agent
```
