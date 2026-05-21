# Ethics Chapter Quiz Fixtures

Use the Canvas mixed-quiz importer for chapter-level instructor quizzes, even
when a chapter contains only multiple-choice questions. This keeps the workflow
uniform as quiz styles vary by chapter. The manifest
`ethics_chapter_quizzes.json` is the source of truth for expected counts,
question-type mix, keyed choice totals, and allowed import warnings.

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
| 3 | `ethics_ch3_canvas_raw.txt` | `ethics_ch3_canvas_answer_key.txt` | `ethics_ch3_canvas.json` | Keyed choice quiz. |

## One-Command Import

Use `import-chapter-quiz` for normal maintenance. It infers the raw, optional
answer-key, and output paths from the manifest, imports the Canvas quiz,
validates mixed quiz shape, checks the chapter contract, and prints unresolved
items such as unkeyed choices, essay prompts, or incomplete matching questions.
The normalized JSON is written only after validation and manifest checks pass.

```bash
uv run ethnos import-chapter-quiz ethics 1
uv run ethnos import-chapter-quiz ethics 2
uv run ethnos import-chapter-quiz ethics 3
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
```

## Validation

```bash
uv run ethnos validate-quiz 1 --quiz benchmarks/ethics_ch1_canvas.json
uv run ethnos validate-quiz 1 --quiz benchmarks/ethics_ch2_canvas.json
uv run ethnos validate-quiz 1 --quiz benchmarks/ethics_ch3_canvas.json
```
