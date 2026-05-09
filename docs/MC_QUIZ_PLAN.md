# Multiple-Choice Quiz Generation and Benchmarking

## Summary

The plan should match existing `ethnos` conventions while producing usable
multiple-choice items: keep `--limit` as retrieval chunk count for `mc-bench`,
add `--max-questions` for quiz truncation, use a 32-token MC default instead of
the normal answer budget, prefer term-based quiz generation by default, support
easy/medium/hard distractor selection, and make scoring work for mixed
keyed/unkeyed quiz files.

## Key Changes

- Add `src/ethnos/quiz.py` with quiz generation, quiz loading/normalization, MC
  prompt building, deterministic option assignment, source-page parsing, and
  distractor sampling.
- Generated quizzes use a versioned JSON object shape with root metadata:
  `version`, `document_id`, `generated_at`, `seed`, `source`, `role`,
  `section`, `difficulty`, `max_option_chars`, record counts, and `questions`.
  `correct` is always present for generated items; external quizzes may omit it
  per item.
- Each generated item includes `source_chunks`, `source_pages`, and
  `source_citation` so quiz files remain understandable outside the original DB.
  Term items also include `target`.
- `generate_quiz(conn, document_id, source="terms", limit=None, seed=None,
  max_option_chars=120, role="core", section=None, difficulty="medium")` reads
  `key_terms`, `questions`, or both, builds same-type distractors, skips items
  with fewer than 3 distractors, and returns document-order items up to `limit`.
- Term-based generation is the default because definitions map more naturally to
  concise MC options. Question-based generation remains available via
  `--source questions` or `--source both`.
- Generated term prompts use `Which definition best matches {term} in this
  text?` so models treat the task as option matching, not free definition.
- Use one `random.Random(seed)` per generation run so distractor and option
  shuffling are reproducible without repeating the same sample for every item.
- Deduplicate correct answers and distractors by `value.strip().lower()` for
  comparison only, while preserving the original display text in quiz options.
- Display option text is capped with an ellipsis at `max_option_chars` to avoid
  paragraph-length MC options; keep the untruncated source text internally for
  deduplication and report/debug metadata.
- Distractor ranking supports `easy`, `medium`, and `hard`. Easy mode prefers
  farther, lower-overlap distractors and skips broad single-word terms when the
  same chunk contains a more specific sibling term. Hard mode prefers
  shared-topic and nearby distractors. Medium stays balanced.
- Batch-load topic names once at the start of `generate_quiz` with a single
  document-scoped query over `topics` joined to `chunks`, building
  `dict[int, set[str]]` keyed by `chunk_id`; use that map for all shared-topic
  distractor scoring instead of querying per item.
- Add `build_mc_prompt(item, context_rows, max_chars, prompt_path=...)`;
  the prompt template formats the user message with question, target term,
  source citation, options block, and target-centered context. `max_chars`
  applies only to retrieved context, not to options.

## CLI And Ollama

- Add `ethnos generate-quiz <document_id> --output <path> [--source
  terms|questions|both] [--difficulty easy|medium|hard] [--limit N] [--seed N]
  [--max-option-chars N] [--role core|support|admin|all] [--section ...]`;
  create output parents like existing export/report commands and print generated
  count plus source/difficulty distributions.
- Add `ethnos mc-bench <document_id> --quiz <path> [--max-questions N]
  [--limit N] [--chars N] [--output <path>] [--role core|support|admin|all]
  [--section ...] [--options-retrieval] [--debug-ollama] [--debug-retrieval]
  [--model M] [--num-predict N] [--num-ctx N]`.
- For `mc-bench`, default `--limit` remains retrieval chunk count, defaulting
  to 3 for tighter MC context after source-context injection. Default
  `--max-questions` is all quiz items, default `--chars` is `900`, and default
  MC `--num-predict` is `32`.
- Add `MCAnswerResult` in `ollama_client.py` with `raw_prompt`, `raw_response`,
  `selected_option`, `validation_status`, `validation_error`, and optional
  `debug_info`.
- Implement `answer_mc_question()` using a new MC-specific structured chat
  request with schema `{selected_option: enum[A,B,C,D]}`.
- Keep the MC system message hardcoded in the Ollama request kwargs builder,
  consistent with the existing extraction and answer request builders.
  `prompts/mc_answer.md` remains only the user-message template formatted by
  `build_mc_prompt()`.
- Force MC calls to `think=False` regardless of global Ollama settings so the
  32-token budget is reserved for the schema output.
- `mc-bench` should reuse one Ollama client, skip model calls when no context is
  found, inject generated quiz source chunks into MC context when available,
  print ASCII statuses like `correct`, `incorrect`, `unkeyed`, or `no_context`,
  and score keyed questions with context only. If no questions have `correct`,
  omit accuracy and report answers only.
- For retrieval, query with the question text alone by default. Only when
  `--options-retrieval` is set should the command retry no-context questions
  with compact question-plus-option text, because option text can bias retrieval
  toward real distractor content.

## Report Shape

- Optional `mc-bench --output` writes JSON with `document_id`, `quiz`, `model`,
  totals, keyed totals, scored total, correct count, accuracy when applicable,
  no-context count, invalid-response count, elapsed seconds, and per-item
  retrieval/model results.
- Per-item report includes `id`, `question`, `options`, `target`,
  `source_record_type`, `source_record_id`, `selected_option`,
  `selected_option_text`, optional `correct`, optional `correct_option_text`,
  optional `is_correct`, `validation_status`, selected chunks/citations,
  queries tried, raw response, and timing.
- `accuracy` denominator is the count of keyed items that had retrieved context
  and a valid model response. Report keyed no-context and invalid-response items
  separately so accuracy cannot hide coverage failures.

## Tests

- Add `tests/test_quiz.py` for option assignment, seed reproducibility,
  correct-answer exclusion, option text truncation, topic/proximity distractor
  preference, source-page parsing, external quiz normalization, MC prompt
  formatting, and DB-backed generation skipping insufficient distractors.
- Add Ollama-client tests for valid MC JSON, invalid JSON, invalid option, and
  request failure using fake clients, including the forced `think=False` MC
  request behavior.
- Add CLI integration tests using a dedicated quiz fixture with at least four
  eligible records, since the existing labeled fixture does not have enough
  distractors.
- Add `generate-quiz` CLI test for versioned JSON metadata, source citation,
  option length cap, and `correct`.
- Add `mc-bench` CLI tests for keyed scoring, unkeyed no-score behavior, mixed
  keyed/unkeyed scoring, `--max-questions`, no-context skip, opt-in
  option-text retrieval, and report output.
- Add prompt test ensuring `prompts/mc_answer.md` asks for context-grounded
  answers and JSON-only output.

## Assumptions

- `source_chunks` in generated quiz items means database chunk IDs from
  `record["chunk_id"]`.
- `source_pages` is parsed from the DB's JSON string into `list[int]`.
- Generated term prompts use `Which definition best matches {term} in this
  text?`, with the term definition as the correct answer and item difficulty
  metadata preserved from the source where available.
- Question-based MC can still produce weaker items when extracted answers are
  paragraph-length or unrelated distractors are easy to reject; benchmark
  results should be interpreted with that limitation.
- LLM-generated distractors and extraction-time `answer_short` fields are phase
  2 ideas, not part of the v1 implementation.
- The verification should not expect a fixed count like `186`; the count depends
  on available eligible records and whether each has at least three unique
  distractors.
