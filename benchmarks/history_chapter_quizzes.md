# History Chapter Quiz Fixtures

Use the standard Canvas mixed-quiz importer for history chapter quizzes, even
when a chapter contains only multiple-choice questions. This keeps the fixture
workflow aligned with ethics and leaves room for mixed Canvas quizzes later.

## File Pattern

- `history_chN_canvas_raw.txt`: pasted Canvas quiz text for chapter `N`.
- `history_chN_canvas_answer_key.txt`: label-style answer key for choice items.
- `history_chN_canvas.json`: normalized `external-quiz-v2` import.
- `history_chapter_quizzes.json`: fixture contract for imported chapters.

## Current Chapters

| Chapter | Raw | Key | Imported | Notes |
| --- | --- | --- | --- | --- |
| 20 | `history_ch20_canvas_raw.txt` | `history_ch20_canvas_answer_key.txt` | `history_ch20_canvas.json` | Keyed choice quiz. Questions 15 and 20 intentionally repeat the New Freedom prompt with different option order. |

## Import And Validate

```bash
uv run ethnos import-chapter-quiz history 20
uv run ethnos validate-quiz 2 --quiz benchmarks/history_ch20_canvas.json
```

Use `--review` on the import command when you want the keyed item listing in
the terminal.

## Source Grounding And Benchmark

```bash
uv run ethnos ground-quiz 2 \
  --quiz benchmarks/history_ch20_canvas.json \
  --output data/runs/history_ch20_grounding.json \
  --options-retrieval

uv run ethnos quiz-bench 2 \
  --quiz benchmarks/history_ch20_canvas.json \
  --chars 900 \
  --output data/runs/history_ch20_key_check.json \
  --options-retrieval

uv run ethnos verify-answer-key data/runs/history_ch20_key_check.json \
  --output data/runs/history_ch20_key_audit.json
```
