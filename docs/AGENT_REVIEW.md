# Agent Review

Agent Review is the model-driven review layer for Ethnos. It lets a local or
hybrid Ollama model inspect quiz items with deterministic Ethnos tools, cite
PDF evidence, flag answer-key risks, and write a CTO-ready report.

The CPU-local path does not depend on the model to do all the work. Each item
gets deterministic preflight grounding first, using the question, keyed answer,
question-plus-key, retrieval hints, target, and option text. This keeps the
review useful when a small local model calls tools imperfectly or fails to
produce a final structured verdict.

Grounding is keyed-answer aware: rows that support the keyed answer are ranked
above broad question-only matches, PDF line-break hyphenation is normalized, and
answer terms are canonicalized for simple spelling/plural variants before a
fallback verdict is accepted.

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
  by a vision-capable model such as Gemma 3.
- `--max-steps 8`: cap the structured tool loop for each quiz item.
- `--debug-agent`: write `tool_trace.jsonl` beside the reports.
- `--model-profile cpu-local|review-local|gemma3-local|gemma3-fast|hybrid-max`:
  choose the model profile and context/output defaults.
- `--profile cto`: convenience alias for the review-ready `review-local`
  profile.

## Outputs

The output directory contains:

- `agent_review.md`: human-readable review.
- `agent_review.json`: structured report with verdicts, evidence, and question
  quality findings.
- `tool_trace.jsonl`: optional model action and tool result trace.

Each run is also persisted to SQLite in `agent_runs` and `agent_findings`.

## Model Profiles

- `cpu-local`: tuned for the current CPU-only baseline with `gemma-python`.
- `review-local`: slightly larger CPU-only review budget with `gemma-python`.
- `gemma3-local`: optional future profile. Targets `gemma3:12b` with
  `gemma3:4b` as the practical fallback.
- `gemma3-fast`: optional smaller Gemma 3 profile for quick checks.
- `hybrid-max`: max-capability profile for explicit web/cloud-assisted review.

Existing `gemma-python` workflows remain the CPU-only baseline for structure
extraction, Q&A, quiz benchmarking, and Agent Review. Gemma 3 profiles are
optional future profiles for hosts where they are practical.

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

For CPU-only hosts, prefer:

```bash
uv run ethnos agent-review 2 \
  --quiz benchmarks/history_ch20_canvas.json \
  --output data/runs/history_ch20_agent_review_cpu \
  --model gemma-python \
  --profile cto \
  --vision-pages off \
  --max-steps 1 \
  --debug-agent
```
