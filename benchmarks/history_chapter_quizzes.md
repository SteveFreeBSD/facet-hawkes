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
| 22 | `history_ch22_canvas_raw.txt` | `history_ch22_canvas_answer_key.txt` | `history_ch22_canvas.json` | Keyed choice quiz covering the New Era; all 20 items have manifest source anchors. |
| 25 | `history_ch25_canvas_raw.txt` | `history_ch25_canvas_answer_key.txt` | `history_ch25_canvas.json` | Keyed Cold War quiz; all 20 items have manifest source anchors. Question 8 retains the instructor key but is marked disputed against the PDF evidence. |
| 27 | `history_ch27_canvas_raw.txt` | `history_ch27_canvas_answer_key.txt` | `history_ch27_canvas.json` | Keyed Sixties quiz. Nineteen items are locally PDF-grounded; Warren Court item 19 is explicitly tagged as missing from the local PDF. |

## Import And Validate

```bash
uv run ethnos import-chapter-quiz history 20
uv run ethnos import-chapter-quiz history 22
uv run ethnos import-chapter-quiz history 25
uv run ethnos import-chapter-quiz history 27
uv run ethnos validate-quiz 2 --quiz benchmarks/history_ch20_canvas.json
uv run ethnos validate-quiz 2 --quiz benchmarks/history_ch22_canvas.json --require-anchors
uv run ethnos validate-quiz 2 --quiz benchmarks/history_ch25_canvas.json --require-anchors
uv run ethnos validate-quiz 2 --quiz benchmarks/history_ch27_canvas.json --require-anchors
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

Chapter 25 can be grounded without an answer key:

```bash
uv run ethnos ground-quiz 2 \
  --quiz benchmarks/history_ch25_canvas.json \
  --output data/runs/history_ch25_grounding.json \
  --options-retrieval
```

Question 8 is intentionally excluded from PDF-grounded accuracy because its
instructor key conflicts with the anchored chapter text. It remains included in
instructor-key agreement and answer-key audit output.

## Chapter 27 Acceptance Run

Run the complete Chapter 27 gate with:

```bash
uv run ethnos import-chapter-quiz history 27

uv run ethnos ground-quiz 2 \
  --quiz benchmarks/history_ch27_canvas.json \
  --output data/runs/history_ch27/grounding.json \
  --limit 3 \
  --chars 360 \
  --role core \
  --options-retrieval \
  --fail-unresolved

uv run ethnos quiz-bench 2 \
  --quiz benchmarks/history_ch27_canvas.json \
  --output data/runs/history_ch27/benchmark.json \
  --model qwen3.5:9b \
  --num-ctx 4096 \
  --num-predict 1536 \
  --answer-retries 1 \
  --limit 3 \
  --chars 900 \
  --role core \
  --options-retrieval

uv run ethnos verify-answer-key data/runs/history_ch27/benchmark.json \
  --output data/runs/history_ch27/key_audit.json

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

The verified 2026-07-19 run produced 19/19 correct grounded answers, 100%
instructor-key agreement on scored items, no conflicts, no invalid responses,
and 19/20 source coverage. Item 19 is not counted as wrong: it is skipped as
`source_missing_in_local_pdf`, because the local textbook does not cover the
Warren Court's criminal-procedure decisions.

The deterministic Agent gate reports 17 `key_supported`, 2
`needs_human_review`, and 1 `source_missing` verdict, with priorities of 6 pass,
13 inspect, and 1 fix. Four instructor-key notes are surfaced as quality
findings; conceptual, partially stated, or editorially qualified evidence stays
inspectable even when the model benchmark answers the item correctly.

Several questions intentionally cross the nominal chapter boundary. Brown v.
Board is grounded in chapter 26, while the Kerner Commission and later Vietnam
items use chapter 28 text. The manifest records source provenance rather than
pretending that every valid answer appears inside chapter 27. Content and
wording findings are documented in
[`examples/history_ch27_e2e_findings.md`](../examples/history_ch27_e2e_findings.md).

## Chapter 25 Targeted Follow-up

After a full Chapter 25 run, rerun only review findings with:

```bash
uv run ethnos quiz-bench 2 \
  --quiz benchmarks/history_ch25_canvas.json \
  --item-id ch25-q001 \
  --item-id ch25-q008 \
  --item-id ch25-q009 \
  --output data/runs/history_ch25-targeted.json \
  --options-retrieval
```
