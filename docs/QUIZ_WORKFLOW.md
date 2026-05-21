# Quiz Grounding And Key Audit Workflow

## Summary

Ethnos treats imported quiz content, answer keys, source grounding, model
answers, and key audits as separate claims. The source-grounding record is the
center of the workflow: it says whether each item is actually supported by the
local PDF, only a retrieval candidate, intentionally external to the PDF,
incomplete, invalidly anchored, or ungrounded.

Recommended chapter workflow:

1. Import a Canvas chapter quiz with `import-chapter-quiz`.
2. Build source-grounding records with `ground-quiz`.
3. Validate the quiz shape with `validate-quiz`.
4. Benchmark PDF-grounded answers with `quiz-bench`.
5. Audit the instructor key with `verify-answer-key`.

The MC-only commands remain for older fixtures and comparison reports, but new
chapter work should use the mixed Canvas and grounding workflow.

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
- `external_source`: the item is tagged `external_source_item`.
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

## Benchmarking

`quiz-bench` answers mixed quizzes from retrieved PDF context:

```bash
uv run ethnos quiz-bench 1 \
  --quiz benchmarks/ethics_ch3_canvas.json \
  --output data/runs/ethics_ch3_key_check.json \
  --options-retrieval
```

It reports:

- `correct` / `incorrect` for keyed choice items.
- `answered_unscored` for unkeyed choice items.
- `drafted` for essays.
- `skipped_incomplete` for incomplete matching items.
- `skipped_external_source` for items tagged `external_source_item`.
- `no_context` when PDF retrieval fails.
- `invalid_response` when the model response cannot be parsed.

Each benchmark item includes a `source_grounding` record so downstream tools can
distinguish a likely wrong key from missing or external source material.

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
- `external_source`: the item is intentionally outside the local PDF.
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

These commands remain available for older MC-only fixtures:

- `import-mc-quiz`
- `review-mc-quiz`
- `validate-mc-quiz`
- `mc-bench`
- `mc-compare`
- `suggest-mc-anchors`

Prefer mixed quiz commands for new work unless you specifically need an
old-style MC-only comparison report.
