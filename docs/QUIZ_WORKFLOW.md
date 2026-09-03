# Quiz Grounding And Key Audit Workflow

## Summary

Ethnos treats imported quiz content, answer keys, source grounding, model
answers, and key audits as separate claims. The source-grounding record is the
center of the workflow: it says whether each item is actually supported by the
local PDF, only a retrieval candidate, missing from the current local PDF
extraction, incomplete, invalidly anchored, or ungrounded.

Recommended chapter workflow:

1. Import a Canvas chapter quiz with `import-chapter-quiz`.
2. Validate the quiz shape and anchors with `validate-quiz`.
3. Build source-grounding records with `ground-quiz`.
4. Benchmark PDF-grounded answers with `quiz-bench`.
5. Audit the instructor key with `verify-answer-key`.

For an already-imported quiz JSON, `quiz-pipeline` runs steps 2 through 5 in
order and stops at the first failed step:

```bash
uv run ethnos quiz-pipeline 1 \
  --quiz benchmarks/ethics_ch3_canvas.json \
  --require-anchors \
  --grounding-output data/runs/ethics_ch3_grounding.json \
  --bench-output data/runs/ethics_ch3_key_check.json \
  --key-audit-output data/runs/ethics_ch3_key_audit.json \
  --options-retrieval
```

Omit `--bench-output` for the cheap validation plus grounding pass. Use
`--resume` with the same command when the benchmark checkpoint exists and needs
to continue.

The MC-only commands remain available for dedicated multiple-choice fixtures
and comparison reports, but new chapter work should use the mixed Canvas and
grounding workflow.

## Chapter Fixtures

Chapter fixtures live under `benchmarks/`:

- `<course>_chN_canvas_raw.txt`: pasted Canvas text.
- `<course>_chN_canvas_answer_key.txt`: optional label-style answer key.
- `<course>_chN_canvas.json`: normalized `external-quiz-v2` import.
- `<course>_chapter_quizzes.json`: manifest contract and item overrides.

Use the manifest for expected counts, allowed warnings, source anchors,
retrieval questions, and source notes. Do not hand-edit normalized JSON when an
anchor, retrieval hint, or warning tag belongs in the manifest.

```bash
uv run ethnos import-chapter-quiz ethics 3
```

`import-chapter-quiz` writes normalized JSON only after the import and manifest
contract pass. It fails loudly instead of clobbering a known-good fixture.
Questions that explicitly request multiple responses, such as “select two,”
are rejected because `external-quiz-v2` currently represents one keyed choice
per item.

Anchor validation checks that chunk IDs are positive integers owned by the
selected document, citations match a declared chunk, and every declared page
falls inside a declared chunk's page range. Target matching uses shared
Unicode-aware normalization: accents, soft hyphens, Unicode dashes, ordinary
hyphens, and PDF line-wrap hyphenation are handled consistently.

## Source Grounding

`ground-quiz` performs a no-model source pass and writes one grounding record
per item:

```bash
uv run ethnos ground-quiz 1 \
  --quiz benchmarks/ethics_ch3_canvas.json \
  --output data/runs/ethics_ch3_grounding.json \
  --options-retrieval
```

Grounding statuses:

- `pdf_grounded`: anchored source chunks/citation validate against the PDF.
- `retrieved_candidate`: no explicit anchor, but retrieval found PDF context.
- `source_missing_in_local_pdf`: the item is tagged `external_source_item`
  because the current local PDF extraction does not contain enough source text
  to score it as grounded.
- `incomplete`: the item is tagged `incomplete_item` or
  `incomplete_matching_item`, such as a truncated Canvas export or missing
  matching pairs.
- `invalid_anchor`: anchor metadata exists but does not validate.
- `ungrounded`: no usable PDF source was found.

Use `--fail-unresolved` when unresolved grounding should fail a review gate.
Unresolved means `ungrounded`, `invalid_anchor`, or `incomplete`.

## Validation

`validate-quiz` checks quiz structure, option labels, true/false shape,
matching completeness when requested, warning tags, and source anchor validity:

```bash
uv run ethnos validate-quiz 1 \
  --quiz benchmarks/ethics_ch3_canvas.json \
  --require-anchors
```

Use `--strict-complete` when incomplete items or other import warnings should
fail validation.

Items tagged `external_source_item`, `incomplete_item`, or
`incomplete_matching_item` are exempt from required anchor fields because they
cannot be evaluated as complete PDF-grounded questions. Any anchor fields that
are present are still validated.

Grounding and benchmarking do not run broad retrieval for those exempt items.
Their empty context and empty `queries_tried` fields are deliberate: unrelated
PDF text must not make an explicitly missing or incomplete source look
supported.

## Benchmarking

`quiz-bench` answers mixed quizzes from retrieved PDF context:

```bash
uv run ethnos quiz-bench 1 \
  --quiz benchmarks/ethics_ch3_canvas.json \
  --output data/runs/ethics_ch3_key_check.json \
  --options-retrieval
```

With `--output`, the report is written atomically after every completed item.
If the process is interrupted, rerun the identical command with `--resume`.
Resume validates the document, quiz, model, item order, and run configuration
before continuing. `verify-answer-key` refuses incomplete checkpoints.

Choice answers receive one bounded consistency retry by default. A retry occurs
when the response is invalid, omits citations, conflicts with deterministic
source guidance, or provides evidence that does not support its selected
letter. The report records `answer_attempts`, `answer_attempt_count`, and
`answer_retry_reasons`; summary fields report retried items and total retries.
Use `--answer-retries 0` to disable retries.

For a cheap follow-up after a full run, repeat `--item-id` to benchmark only the
items that need another pass:

```bash
uv run ethnos quiz-bench 2 \
  --quiz benchmarks/history_ch25_canvas.json \
  --item-id ch25-q001 \
  --item-id ch25-q008 \
  --item-id ch25-q009 \
  --output data/runs/history_ch25-targeted.json \
  --options-retrieval
```

Targeted reports are complete reports for their selected subset and can be
passed directly to `verify-answer-key`. `--item-id` and `--max-questions` are
mutually exclusive.

When a quiz item has validated `source_chunks`, those anchors are the complete
model and Agent Review context. Broad retrieval is not run, and unrelated
chunks are not mixed into the answer prompt. All declared anchors are retained
in manifest order even when their count is larger than the ordinary retrieval
limit.

Source-derived guidance handles negative questions, anchored target phrases,
percentage complements, and compound options. “All of the above,” “All possible
answers,” and “All of the possible answers” are equivalent compound forms; the
compound label is recommended only when every individual option is supported.

It reports:

- `correct` / `incorrect` for keyed choice items.
- `answered_unscored` for unkeyed choice items.
- `drafted` for essays.
- `skipped_incomplete` for incomplete items.
- `skipped_source_missing` for items whose quiz source cannot be found in the
  current local PDF extraction.
- `invalid_anchor` when declared source metadata fails validation. These items
  do not reach the answer model and are not scoring-eligible.
- `no_context` when PDF retrieval fails.
- `invalid_response` when the model response cannot be parsed.

Each benchmark item includes a `source_grounding` record so downstream tools can
distinguish a likely wrong key from missing local PDF source material.
Benchmark summaries separate `grounded accuracy` from `source coverage`; this
keeps model correctness and source availability honest. Only `pdf_grounded`
and `retrieved_candidate` items count as covered. Source-missing and incomplete
items remain in the total, so a 19-grounded/1-source-missing quiz reports 95%
coverage rather than 100%. Invalid anchors are excluded from grounded accuracy
and use `is_correct: null`, rather than being counted as model mistakes.

When an instructor key is known but conflicts with the available PDF evidence,
set `key_review_status` to `disputed` in the manifest override and explain the
issue in `instructor_key_note`. The item remains visible in instructor-key
agreement and key-audit findings, but is excluded from grounded accuracy.

## Answer-Key Audit

`verify-answer-key` reads a `quiz-bench` report and audits keyed choice items:

```bash
uv run ethnos verify-answer-key data/runs/ethics_ch3_key_check.json \
  --output data/runs/ethics_ch3_key_audit.json
```

Audit statuses:

- `key_supported`: benchmark selected the keyed option with valid context.
- `key_conflict_candidate`: benchmark selected a different option with valid
  PDF evidence.
- `no_pdf_context`: no source context was found, so the key cannot be judged.
- `source_missing_in_local_pdf`: the key may be correct, but the current local
  PDF extraction does not provide source text to judge it.
- `incomplete`: the keyed item was skipped because the imported question is
  incomplete.
- `invalid_anchor`: declared chunk, page, target, or citation metadata failed
  validation, so neither the answer nor the key can be source-audited safely.
- `invalid_response`: model output was not valid enough to judge the key.
- `unclassified`: any remaining status that needs human review.

The command exits nonzero when it finds a `key_conflict_candidate` or
`invalid_anchor`, making wrong keys and broken provenance fail a review gate.

## Generated Quizzes

Generated quizzes still use `generate-quiz`:

```bash
uv run ethnos generate-quiz 1 \
  --output data/runs/ethics_generated.json \
  --source terms \
  --difficulty medium
```

Generated items already include source chunks, pages, citations, targets, and
option provenance. They can go through the same `ground-quiz`, `quiz-bench`,
and `verify-answer-key` pipeline.

## Compatibility Commands

These commands remain available for dedicated MC-only fixtures:

- `import-mc-quiz`
- `review-mc-quiz`
- `validate-mc-quiz`
- `mc-bench`
- `mc-compare`
- `suggest-mc-anchors`

Prefer mixed quiz commands for new work unless you specifically need an
MC-only comparison report.
