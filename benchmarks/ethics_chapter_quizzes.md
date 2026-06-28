# Ethics Chapter Quiz Fixtures

Use the Canvas mixed-quiz importer for chapter-level instructor quizzes, even
when a chapter contains only multiple-choice questions. This keeps the workflow
uniform as quiz styles vary by chapter. The manifest
`ethics_chapter_quizzes.json` is the source of truth for expected counts,
question-type mix, keyed choice totals, allowed import warnings, and any item
overrides needed for source anchors or retrieval hints.

## File Pattern

- `ethics_chN_canvas_raw.txt`: pasted Canvas quiz text for chapter `N`.
- `ethics_chN_canvas_answer_key.txt`: optional keyed labels for choice items.
- `ethics_chN_canvas.json`: normalized `external-quiz-v2` import.
- `ethics_chapter_quizzes.json`: fixture contract for all imported chapters.

## Current Chapters

| Chapter | Raw | Key | Imported | Notes |
| --- | --- | --- | --- | --- |
| 1 | `ethics_ch1_canvas_raw.txt` | `ethics_ch1_canvas_answer_key.txt` | `ethics_ch1_canvas.json` | Keyed choice quiz. |
| 2 | `ethics_ch2_canvas_raw.txt` | none yet | `ethics_ch2_canvas.json` | Mixed quiz with unkeyed choice items, one incomplete matching item, and essay prompts. |
| 3 | `ethics_ch3_canvas_raw.txt` | `ethics_ch3_canvas_answer_key.txt` | `ethics_ch3_canvas.json` | Keyed choice quiz with manifest source anchors. |
| 5 | `ethics_ch5_canvas_raw.txt` | `ethics_ch5_canvas_answer_key.txt` | `ethics_ch5_canvas.json` | Keyed utilitarianism quiz; nine items are PDF-anchored and question 1 is explicitly external-source. |

## One-Command Import

Use `import-chapter-quiz` for normal maintenance. It infers the raw, optional
answer-key, and output paths from the manifest, imports the Canvas quiz,
validates mixed quiz shape, checks the chapter contract, and prints unresolved
items such as unkeyed choices, essay prompts, or incomplete matching questions.
The normalized JSON is written only after validation and manifest checks pass.
Use manifest `item_overrides` to attach source anchors, retrieval questions,
warning tags, or notes without hand-editing the normalized JSON.

Chapter 3 question 9 is tagged `external_source_item`, with review status
`source_missing_in_local_pdf`: the St. Catherine/Maxentius source text is not
present in the current local `ethics.pdf` extraction. Quiz benchmarking reports
it as source coverage missing instead of counting it as a model error or a PDF
no-context failure.

Chapter 5 question 1 is also tagged `external_source_item`: the exact “needs of
the many” wording is associated with *Star Trek* and is absent from the local
PDF, while the instructor key identifies Jeremy Bentham. Questions 2–10 are
anchored to chapter 5 source chunks. Question 9 is keyed as “both a and b”; the
PDF directly supports the beer comparison but does not literally call *Hamlet*
boring, so it is marked `key_review_status: disputed`. It remains in
instructor-key agreement and audit results but is excluded from grounded
accuracy.

```bash
uv run ethnos import-chapter-quiz ethics 1
uv run ethnos import-chapter-quiz ethics 2
uv run ethnos import-chapter-quiz ethics 3
uv run ethnos import-chapter-quiz ethics 5
```

Use `--review` when you want the full keyed/unkeyed item listing after import.

## Direct Import Commands

The lower-level commands remain useful when creating or debugging fixtures by
hand:

```bash
uv run ethnos import-canvas-quiz benchmarks/ethics_ch1_canvas_raw.txt \
  --answer-key benchmarks/ethics_ch1_canvas_answer_key.txt \
  --output benchmarks/ethics_ch1_canvas.json \
  --document-id 1 \
  --title "Quiz CH 1" \
  --id-prefix ch1-q

uv run ethnos import-canvas-quiz benchmarks/ethics_ch2_canvas_raw.txt \
  --output benchmarks/ethics_ch2_canvas.json \
  --document-id 1 \
  --title "Quiz CH 2" \
  --id-prefix ch2-q

uv run ethnos import-canvas-quiz benchmarks/ethics_ch3_canvas_raw.txt \
  --answer-key benchmarks/ethics_ch3_canvas_answer_key.txt \
  --output benchmarks/ethics_ch3_canvas.json \
  --document-id 1 \
  --title "Quiz CH 3" \
  --id-prefix ch3-q

uv run ethnos import-canvas-quiz benchmarks/ethics_ch5_canvas_raw.txt \
  --answer-key benchmarks/ethics_ch5_canvas_answer_key.txt \
  --output benchmarks/ethics_ch5_canvas.json \
  --document-id 1 \
  --title "Ethics Chapter 5 Quiz" \
  --id-prefix ch5-q
```

## Validation

```bash
uv run ethnos validate-quiz 1 --quiz benchmarks/ethics_ch1_canvas.json
uv run ethnos validate-quiz 1 --quiz benchmarks/ethics_ch2_canvas.json
uv run ethnos validate-quiz 1 --quiz benchmarks/ethics_ch3_canvas.json
uv run ethnos validate-quiz 1 --quiz benchmarks/ethics_ch5_canvas.json --require-anchors
```

## Source Grounding

Build the source-grounding report before running model-backed checks:

```bash
uv run ethnos ground-quiz 1 \
  --quiz benchmarks/ethics_ch3_canvas.json \
  --output data/runs/ethics_ch3_grounding.json \
  --options-retrieval
```

The grounding report is the canonical per-item source state. It distinguishes
PDF-grounded questions from retrieved candidates, source-missing questions,
incomplete matching items, invalid anchors, and ungrounded items.

## Answer-Key Audit

Use `quiz-bench` to produce PDF-grounded selections, then audit the key:

```bash
uv run ethnos quiz-bench 1 \
  --quiz benchmarks/ethics_ch3_canvas.json \
  --output data/runs/ethics_ch3_key_check.json \
  --options-retrieval

uv run ethnos verify-answer-key data/runs/ethics_ch3_key_check.json \
  --output data/runs/ethics_ch3_key_audit.json
```

`verify-answer-key` separates likely wrong keys from other cases:

- `key_conflict_candidate`: PDF-backed selection disagrees with the key.
- `no_pdf_context`: no source context was found, so the key cannot be judged.
- `source_missing_in_local_pdf`: the key may be correct, but the current local
  PDF extraction does not provide source text to judge it.
