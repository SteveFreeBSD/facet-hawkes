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
- `incomplete`: the item is incomplete, such as missing matching pairs.
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

Use `--strict-complete` when incomplete matching items or other import warnings
should fail validation.

An item tagged `external_source_item` is exempt from required anchor fields
because its source is explicitly absent from the local PDF. Any anchor fields
that are present are still validated.

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

When a quiz item has validated `source_chunks`, those anchors are the complete
model context. Retrieval queries and candidates remain in diagnostics, but
unrelated retrieved chunks are not mixed into the answer prompt.

It reports:

- `correct` / `incorrect` for keyed choice items.
- `answered_unscored` for unkeyed choice items.
- `drafted` for essays.
- `skipped_incomplete` for incomplete matching items.
- `skipped_source_missing` for items whose quiz source cannot be found in the
  current local PDF extraction.
- `no_context` when PDF retrieval fails.
- `invalid_response` when the model response cannot be parsed.

Each benchmark item includes a `source_grounding` record so downstream tools can
distinguish a likely wrong key from missing local PDF source material.
Benchmark summaries separate `grounded accuracy` from `source coverage`; this
keeps model correctness and source availability honest.

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
- `invalid_response`: model output was not valid enough to judge the key.
- `unclassified`: any remaining status that needs human review.

The command exits nonzero when it finds a `key_conflict_candidate`, making wrong
answer keys easy to catch in a review gate.

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
