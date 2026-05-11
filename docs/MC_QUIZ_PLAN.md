# Multiple-Choice Quiz Generation and Benchmarking

## Summary

Ethnos supports local multiple-choice quiz generation, external LMS quiz import,
pre-flight validation, source-anchor suggestion, and Ollama-backed MC
benchmarking. The workflow now covers both generated quizzes and instructor/LMS
quizzes:

1. Generate or import a quiz.
2. Apply or review the answer key.
3. Validate quiz shape, keys, and anchors before model calls.
4. Suggest source anchors for sparse external items.
5. Benchmark against retrieved PDF context.

`generate-quiz --difficulty` controls distractor selection for generated items;
it is not a root default for all quiz items. Source records can still carry their
own item difficulty metadata, and external quizzes may omit difficulty entirely.

## Generated Quiz Workflow

- `ethnos generate-quiz <document_id> --output <path> [--source
  terms|questions|both] [--difficulty easy|medium|hard] [--limit N] [--seed N]
  [--max-option-chars N] [--role core|support|admin|all] [--section ...]`
  writes a versioned JSON quiz and creates output parents like other export
  commands.
- Generated quizzes use root metadata: `version`, `document_id`,
  `generated_at`, `seed`, `source`, `role`, `section`, `max_option_chars`,
  `difficulty`, `record_counts`, `generated_count`,
  `skipped_insufficient_distractors`, `skipped_display_collision`, and
  `questions`.
- Term-based generation is the default because definitions map naturally to
  concise MC options. Question-based generation remains available via
  `--source questions` or `--source both`.
- Generated term prompts use `Which definition best matches {term} in this
  text?`; term items include `target`, `source_record_type`,
  `source_record_id`, `source_chunks`, `source_pages`, and `source_citation`.
- Generation uses one `random.Random(seed)` per run so distractor selection and
  option shuffling are reproducible.
- Distractor ranking supports `easy`, `medium`, and `hard`. Easy mode prefers
  farther, lower-overlap distractors and skips broad single-word terms when a
  more specific sibling term exists in the same chunk. Hard mode prefers
  shared-topic and nearby distractors. Medium stays balanced.
- Correct answers and distractors are deduplicated by normalized raw text and by
  normalized display text after `max_option_chars` truncation. Items skipped
  because too few distractors survive are counted separately from items skipped
  because display truncation caused collisions.

## External LMS Quiz Workflow

- `ethnos import-mc-quiz <input> --output <path> [--answer-key <path>]
  [--document-id N] [--title T] [--id-prefix PREFIX] [--with-key-preview]`
  converts copied LMS quiz text into `external-mc-v1` JSON.
- The importer parses numbered questions, labeled options, exact-answer answer
  keys, and label-style keys such as `1 B`. `--with-key-preview` prints the
  applied key so the imported file can be audited immediately.
- External items require `id`, `question`, and 2 to 6 labeled options starting
  at `A`. `correct` is optional, allowing unkeyed answer collection.
- `question_type` defaults to `multiple_choice`. Items with exactly `A=True`
  and `B=False` are normalized as `true_false`; explicit `true_false` items must
  use that two-option shape.
- External items may include `source_chunks`, `source_pages`,
  `source_citation`, and `target` so sparse instructor questions can be grounded
  in the source PDF before benchmarking.
- External items may also include `retrieval_questions` custom FTS queries used
  by anchor suggestion and benchmarking instead of relying only on the quiz
  question text. The older `retrieval_queries` field remains accepted as an
  alias.

## Validation And Anchoring

- `ethnos review-mc-quiz <quiz> [--max-questions N]` prints keyed answers for a
  quick human audit.
- `ethnos validate-mc-quiz <document_id> --quiz <path> [--max-questions N]
  [--require-anchors]` is the no-Ollama pre-flight gate. It validates option
  labels, answer keys, true/false shape, duplicate option text, and, with
  `--require-anchors`, requires `target`, `source_chunks`, `source_pages`, and
  `source_citation` on every item.
- `ethnos suggest-mc-anchors <document_id> --quiz <path> [--max-questions N]
  [--limit N] [--chars N] [--role core|support|admin|all] [--section ...]
  [--output <path>]` uses local FTS retrieval to propose `source_chunks`,
  `source_pages`, `source_citation`, and `target` for external quiz items.
- The recommended external-quiz pipeline is:

```bash
uv run ethnos import-mc-quiz benchmarks/ethics_ch1_mc_raw.txt \
  --answer-key benchmarks/ethics_ch1_mc_answer_key.txt \
  --output data/runs/ethics_ch1_mc_imported.json \
  --document-id 1 \
  --id-prefix ch1-q \
  --with-key-preview

uv run ethnos validate-mc-quiz 1 \
  --quiz data/runs/ethics_ch1_mc_imported.json \
  --require-anchors

uv run ethnos suggest-mc-anchors 1 \
  --quiz data/runs/ethics_ch1_mc_imported.json \
  --output data/runs/ethics_ch1_anchor_suggestions.json

uv run ethnos mc-bench 1 \
  --quiz data/runs/ethics_ch1_mc_imported.json \
  --output data/runs/mc-bench-ethics-ch1.json
```

## MC Benchmarking

- `ethnos mc-bench <document_id> --quiz <path> [--max-questions N]
  [--limit N] [--chars N] [--output <path>] [--role core|support|admin|all]
  [--section ...] [--options-retrieval] [--debug-ollama] [--debug-retrieval]
  [--model M] [--num-predict N] [--num-ctx N]` benchmarks MC items against
  retrieved local PDF context.
- `--limit` remains retrieval chunk count and defaults to 3 for tighter MC
  context after source-context injection. `--max-questions` truncates quiz item
  count. `--chars` defaults to `900`, and MC `--num-predict` defaults to `32`.
- `mc-bench` reuses one Ollama client, injects generated or anchored
  `source_chunks` into context when available, skips model calls when no context
  is found, and prints ASCII statuses such as `correct`, `incorrect`,
  `unkeyed`, or `no_context`.
- Retrieval uses `retrieval_questions` or `retrieval_queries` when present,
  otherwise the question text. `--options-retrieval` is opt-in and retries
  no-context items with compact question-plus-option text because option text can
  bias retrieval toward distractor content.
- The MC prompt includes question type, target term, source citation, options,
  and target-centered context. The Ollama request forces `think=False` and uses a
  structured `{selected_option: enum[...]}` response.

## Report Shape

- Optional `mc-bench --output` writes JSON with `document_id`, `quiz`, `model`,
  totals, keyed totals, scored total, correct count, accuracy when applicable,
  no-context count, invalid-response count, elapsed seconds, and per-item
  retrieval/model results.
- Per-item reports include `id`, `question`, `options`, `target`,
  `source_record_type`, `source_record_id`, `selected_option`,
  `selected_option_text`, optional `correct`, optional `correct_option_text`,
  optional `is_correct`, `validation_status`, selected chunks/citations,
  retrieval queries tried, raw response, and timing.
- `accuracy` denominator is keyed items that had retrieved context and a valid
  model response. No-context and invalid-response counts are reported separately
  so accuracy cannot hide coverage failures.

## Cross-Run Comparison

- `ethnos mc-compare <baseline.json> <candidate.json> [--output <path>]`
  compares two `mc-bench --output` reports.
- The comparison reports baseline/candidate accuracy, accuracy delta, common,
  added, and removed question counts, correctness flips, selected-answer
  changes, and retrieval changes.
- Per-item comparison details include question id, status before/after,
  selected options and option text, correct option, selected chunks, and
  retrieval queries.

## Backlog

- Expand `generate-quiz` aggregate statistics beyond skip counts: distractor
  pool utilization, average/max option length after truncation, and topic
  coverage.
- Add selected distractor provenance to wrong MC results, such as
  `selected_distractor_source_record_id`, so repeated runs can build a concept
  confusion matrix.
- Add `mc-bench --models model_a,model_b` to match `qa-bench` model comparison
  and report side-by-side accuracy, agreement, and speed.
- Add quiz diff tooling for regression testing extraction changes with a fixed
  `generate-quiz --seed`.
- Consider `export-flashcards` for Anki-compatible cards using question front,
  correct answer plus explanation back, difficulty metadata, and
  `source_citation`.

## Usage Ideas

- Progressive difficulty ladder: generate easy, medium, and hard quizzes with
  the same seed, then benchmark each to build a difficulty calibration curve.
  A steep easy-to-medium drop suggests retrieval weakness; a medium-to-hard drop
  suggests the model struggles to distinguish closely related concepts.
- Instructor quiz calibration: import an LMS quiz, key it, validate anchors,
  suggest source grounding, and benchmark. Gaps between generated quizzes and
  instructor quizzes reveal concepts the extractor missed or underweighted.
- Chapter-scoped quiz batteries: combine `--section`, `--role`, and imported
  chapter quizzes to compare generated chapter coverage against instructor test
  coverage.
- Quiz diff between extractions: after changing extraction models or prompts,
  regenerate with the same seed and inspect new terms, changed definitions, and
  distractor pool changes.

## Tests

- `tests/test_quiz.py` covers generated quiz metadata, option assignment, seed
  reproducibility, correct-answer exclusion, option truncation, display
  collision handling, topic/proximity distractor preference, source-page
  parsing, true/false normalization, LMS import, validation, anchor suggestion,
  MC prompt formatting, and DB-backed generation skipping.
- Ollama-client tests cover valid MC JSON, invalid JSON, invalid options,
  request failure, and forced `think=False` MC request behavior.
- CLI tests cover `generate-quiz`, `import-mc-quiz`, `validate-mc-quiz`,
  `suggest-mc-anchors`, `mc-bench`, and `mc-compare` behavior including keyed
  scoring, unkeyed no-score behavior, mixed keyed/unkeyed scoring,
  `--max-questions`, no-context skip, opt-in option-text retrieval, report
  output, accuracy deltas, correctness flips, answer changes, and retrieval
  changes.

## Assumptions

- `source_chunks` means database chunk IDs.
- `source_pages` is parsed into `list[int]`.
- Generated term prompts use the term definition as the correct answer and
  preserve item difficulty metadata from the source where available.
- Question-based MC can produce weaker items when extracted answers are
  paragraph-length or unrelated distractors are easy to reject; benchmark
  results should be interpreted with that limitation.
- LLM-generated distractors and extraction-time `answer_short` fields remain
  phase 2 ideas.
