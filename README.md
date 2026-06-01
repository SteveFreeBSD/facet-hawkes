# ethnos

`ethnos` is a local-first AI study and review system for PDF course material.
It ingests source PDFs, builds structured searchable knowledge, answers
questions with cited local context, imports real Canvas/LMS quizzes, benchmarks
model performance, audits answer keys, and produces CTO-ready Agent Review
reports.

The design goal is deliberately serious: every model-facing claim should be
traceable back to local source text, every transformation should be inspectable,
and every report should separate model behavior from source quality.

## Why It Stands Out

- **Local-first by default**: SQLite, FTS5, PyMuPDF, Pydantic v2, and Ollama
  run on the workstation without sending course material to a hosted service.
- **Auditable model outputs**: prompts, raw responses, validation status,
  normalized records, source pages, citations, and traces are preserved.
- **Agent Review**: quiz items are reviewed with deterministic PDF tools,
  evidence strength, confidence scoring, distractor audit, quality findings, and
  pass/inspect/fix priorities.
- **Real quiz workflows**: Canvas-style mixed quizzes, answer keys, true/false,
  essays, incomplete matching items, generated quizzes, source grounding, and
  benchmark reports all use one coherent pipeline.
- **CPU-aware model strategy**: the current baseline is tuned for the
  Gemma 4 based `gemma-python` alias on CPU-only local hardware; heavier local
  or hybrid profiles are optional, explicit, and benchmark-gated.
- **Review-ready engineering**: `src/` layout, modular CLI commands, Pydantic
  schemas, SQLite WAL/FTS5, safe SQL identifiers, centralized Ollama client,
  retry backoff, formatter/linter/dead-code checks, and 194 passing tests.

## Flagship Result

The checked-in History chapter 20 example shows the current Agent Review story:

```text
20 quiz items reviewed
20 keyed answers source-supported
17 pass
3 inspect
0 fix
quality findings: duplicate_prompt 2, typo 1
evidence strength: direct 8, strong 7, partial 5
```

See [`examples/history_ch20_agent_review_summary.md`](examples/history_ch20_agent_review_summary.md)
for the compact review artifact.

## Core Stack

- `uv` for project and dependency management
- Python `>=3.11` with a `src/` package layout
- PyMuPDF for PDF text extraction
- Pydantic v2 for schemas and JSON validation
- SQLite with WAL and FTS5 for local storage/search
- Ollama Python client for structured local model calls
- Ruff, pytest, compileall, and Vulture for verification

## Setup

Install `uv`, then run:

```bash
uv sync --extra dev
```

The app has sensible local defaults in code. When a host needs explicit
settings, copy [`.env.example`](.env.example) to `.env` and edit only the values
that differ on that machine.

## Quick Demo

Run a source-grounded review over the included History chapter 20 quiz:

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

The generated report writes:

- `agent_review.md`: human-readable review queue
- `agent_review.json`: structured verdicts, confidence, evidence strength,
  distractor audit, and quality findings
- `tool_trace.jsonl`: optional tool/action trace when `--debug-agent` is set

## Basic Use

```bash
uv run ethnos ingest-pdf path/to/course.pdf
uv run ethnos documents
uv run ethnos chunk 1
uv run ethnos label-sections 1 --preset ethics
uv run ethnos section-status 1
uv run ethnos search "photosynthesis"
uv run ethnos inspect-chunk 1 80 --records
uv run ethnos records 1 --type key_terms --role core --limit 10
uv run ethnos quality-report 1
uv run ethnos context 1 "methodological ethical naturalism" --limit 3
uv run ethnos ask 1 "What is methodological ethical naturalism?"
uv run ethnos chat 1
uv run ethnos qa-bench 1 --benchmark benchmarks/ethics_qa.json --no-ask
uv run ethnos agent-review 2 --quiz benchmarks/history_ch20_canvas.json --output data/runs/history_ch20_agent_review --model gemma-python --profile cto
uv run ethnos export-markdown 1
uv run ethnos export-study 1 --output data/processed/study-guide.md
```

For a small Ollama smoke test, limit `structure` to one chunk:

```bash
uv run ethnos structure 1 --limit 1 --debug-ollama
```

`chunk` validates sizing options before writing chunks: `--target-chars` and
`--max-chars` must be positive, `--target-chars` cannot exceed `--max-chars`,
and `--overlap-chars` must be non-negative and smaller than `--max-chars`.

Known local source documents have manual presets: use `--preset ethics` for
`ethics.pdf` and `--preset history` for `history.pdf`. Apply section labels
before structured extraction when rebuilding from source PDFs.

By default, `structure` processes core/unlabeled chunks that have never been
attempted, skipping admin/support chunks to avoid spending Ollama time on
non-study material. Use `--all-roles` when you intentionally want structured
outputs for every labeled chunk. Use `--retry-failed` to retry chunks whose
latest model output failed, and use `--force` only when you intentionally want
to reprocess chunks that already have a valid model output. Raw model outputs
and extraction-run history are preserved.

The default structured-output budget is `2048` tokens. Override it with:

```bash
uv run ethnos structure 1 --num-predict 3072
```

Markdown export can write to a file to avoid flooding the terminal:

```bash
uv run ethnos export-markdown 1 --output data/processed/ethics.md
```

## Developer Notes

The CLI is implemented as a package under `src/ethnos/cli/`. The entrypoint is
`ethnos.cli:main`, and `build_parser()` lives alongside it in
`cli/__init__.py`. Re-exports in `ethnos.cli` keep test imports and
monkeypatch paths stable.

## Inspecting Assimilated Knowledge

`section_label` names the kind of document section, such as `chapter_content`,
`chapter_references`, `front_matter`, or `accessibility`. `content_role` is a
broader bucket for filtering: `core`, `support`, `admin`, `artifact`, or
`unknown`.

Inspect one chunk:

```bash
uv run ethnos inspect-chunk 1 80
uv run ethnos inspect-chunk 1 80 --full-text
uv run ethnos inspect-chunk 1 80 --records
```

Filter full-text search by section metadata:

```bash
uv run ethnos search "evolutionary ethics" --role core
uv run ethnos search "references" --section chapter_references
```

List normalized structured records:

```bash
uv run ethnos records 1 --type key_terms --role core --limit 10
uv run ethnos records 1 --type questions --section chapter_content --limit 10
uv run ethnos records 1 --chunk-id 80
```

Summarize the shape and quality of the assimilated data without calling Ollama:

```bash
uv run ethnos section-status 1
uv run ethnos structure-status 1
uv run ethnos quality-report 1
```

Rebuild the local SQLite FTS5 search index if recovery is ever needed:

```bash
uv run ethnos rebuild-fts
```

Show retrieval-ready context for a query without asking a model:

```bash
uv run ethnos context 1 "methodological ethical naturalism" --limit 3
uv run ethnos context 1 "license" --role admin --chars 500
```

Ask a local model a grounded question using retrieved PDF context:

```bash
uv run ethnos ask 1 "What is methodological ethical naturalism?"
uv run ethnos ask 1 "What are the main ideas in evolutionary ethics?" --limit 4
uv run ethnos ask 1 "Tell me about the accessibility checklist" --role all --limit 3
uv run ethnos ask 1 "What is virtue ethics?" --trace-dir data/runs
```

`ask` uses local Ollama only. It retrieves FTS5 context first, defaults to
`--role core`, sends only the selected context and question to the model, and
does not mutate the database. Use `--role all` to search across all labeled
roles.

The current default working model is `gemma-python`, with temperature `0`, an
answer budget from `ETHNOS_OLLAMA_ANSWER_NUM_PREDICT` (`1536` by default), and
context from `ETHNOS_OLLAMA_NUM_CTX` (`8192` by default). Override the model or
context window per call:

```bash
uv run ethnos ask 1 "What is virtue ethics?" --model gemma-python
uv run ethnos ask 1 "What is virtue ethics?" --num-ctx 32768
```

Start a simple local terminal loop with the same retrieval and answer path:

```bash
uv run ethnos chat 1
uv run ethnos chat 1 --role core --limit 4 --trace-dir data/runs
```

In chat mode, type a question and press Enter. Type `quit`, `exit`, or `:q` to
leave. Empty input is ignored.

Use `--trace-dir` with `ask` or `chat` when you want inspectable local JSON
traces of answered questions. Traces include the question, derived retrieval
queries, selected chunks, citations, model name, answer text, timings, and
compact Ollama response diagnostics. They are not written by default. Keep them
under `data/runs/` so they stay local and ignored by git.

```bash
uv run ethnos inspect-trace data/runs/<trace-file>.json
uv run ethnos inspect-trace data/runs/<trace-file>.json --show-answer
```

The full quiz workflow is documented in
[`docs/QUIZ_WORKFLOW.md`](docs/QUIZ_WORKFLOW.md).

The project baseline, Agent Review design, migration checklist, performance
guide, and host profiles are documented in:

- [`docs/CTO_REVIEW.md`](docs/CTO_REVIEW.md)
- [`docs/CURRENT_BASELINE.md`](docs/CURRENT_BASELINE.md)
- [`docs/AGENT_REVIEW.md`](docs/AGENT_REVIEW.md)
- [`docs/MIGRATION.md`](docs/MIGRATION.md)
- [`docs/OLLAMA_TROUBLESHOOTING.md`](docs/OLLAMA_TROUBLESHOOTING.md)
- [`docs/PERFORMANCE_TUNING.md`](docs/PERFORMANCE_TUNING.md)
- [`docs/TRACE_DEBUGGING.md`](docs/TRACE_DEBUGGING.md)
- [`docs/hosts/`](docs/hosts/)
- [`examples/`](examples/)

Run the local retrieval-only benchmark without calling Ollama:

```bash
uv run ethnos qa-bench 1 --benchmark benchmarks/ethics_qa.json --no-ask
```

Generate a local multiple-choice quiz from extracted records:

```bash
uv run ethnos generate-quiz 1 \
  --source terms \
  --difficulty easy \
  --output data/runs/mc-quiz-terms-easy.json \
  --limit 20 \
  --seed 42
```

`--difficulty` controls distractor selection. `easy` uses farther, lower-overlap
distractors. `medium` is balanced and prefers nearby context outside the source
chunk before same-chunk sibling terms. Both `easy` and `medium` skip broad
single-word terms when a more specific sibling term is present in the same
chunk, while `hard` keeps the closest shared-topic distractors.

`generate-quiz` writes `quality_stats` metadata and prints the same summary:
skipped item counts, distractor-pool utilization, option length average/max,
topic coverage, section coverage, and source-chunk coverage. Generated items
also include `option_sources` so benchmark reports can trace wrong distractor
choices back to their source term/question, target, and citation.

Run a quiz benchmark with local Ollama:

```bash
uv run ethnos quiz-bench 1 \
  --quiz data/runs/mc-quiz-terms-easy.json \
  --output data/runs/quiz-bench-terms-easy.json \
  --debug-retrieval
```

External quiz files can also be used. They are JSON objects with a `questions`
list; each item needs `question`. Choice items need 2 to 6 labeled options
starting at `A`; untyped items without options are normalized as essays. Include
`correct` only for multiple-choice or true/false items when an answer key is
available. `question_type` is normalized as `multiple_choice` when options are
present; options `A=True` and `B=False` are auto-detected as `true_false`.
Sparse real-world quiz questions can include `retrieval_questions` to point
retrieval at the relevant PDF language.

Copied LMS quiz text can be converted into that JSON shape:

```bash
uv run ethnos import-mc-quiz benchmarks/ethics_ch1_mc_raw.txt \
  --answer-key benchmarks/ethics_ch1_mc_answer_key.txt \
  --output data/runs/ethics_ch1_mc_imported.json \
  --document-id 1 \
  --id-prefix ch1-q \
  --with-key-preview
```

Answer keys can be one exact answer text per choice question, or numbered labels
such as `1 B`. Canvas numbered keys must reference existing choice questions;
bad positions and non-choice targets fail import instead of being ignored.
Review the imported JSON before benchmarking; add `retrieval_questions` manually
for sparse questions when the quiz wording does not contain enough PDF search
language.

Canvas-style pasted quizzes with mixed item types can be converted into
`external-quiz-v2` JSON:

```bash
uv run ethnos import-canvas-quiz benchmarks/canvas_mixed_quiz_raw.txt \
  --output data/runs/canvas-mixed.json \
  --document-id 1 \
  --id-prefix canvas-q \
  --with-key-preview
```

The mixed importer preserves Canvas question positions and point values, strips
`Flag question` and `Group of answer choices` boilerplate, detects MC,
true/false, matching, and essay items, and keeps incomplete matching questions
with warnings. Use the generic review, validation, and benchmark commands for
mixed quizzes:

```bash
uv run ethnos review-quiz data/runs/canvas-mixed.json

uv run ethnos validate-quiz 1 \
  --quiz data/runs/canvas-mixed.json \
  --strict-complete

uv run ethnos quiz-bench 1 \
  --quiz data/runs/canvas-mixed.json \
  --output data/runs/canvas-mixed-bench.json
```

`quiz-bench` scores keyed MC/true-false items, answers unkeyed choice items
without counting them toward accuracy, drafts source-grounded essay answers with
rubrics, and skips incomplete matching items without calling Ollama.

For a quick key audit before spending any Ollama time, use the generic review
command:

```bash
uv run ethnos review-quiz benchmarks/ethics_ch1_mc.json --max-questions 10
```

Validate keys and source anchors before benchmarking:

```bash
uv run ethnos validate-quiz 1 \
  --quiz benchmarks/ethics_ch1_mc.json \
  --require-anchors
```

For a newly imported quiz, get no-Ollama source-anchor suggestions before editing
the quiz JSON:

```bash
uv run ethnos suggest-mc-anchors 1 \
  --quiz data/runs/ethics_ch1_mc_imported.json \
  --output data/runs/ethics_ch1_anchor_suggestions.json
```

```json
{
  "version": "external-mc-v1",
  "questions": [
    {
      "id": "q001",
      "question": "What does 'reductio ad absurdum' mean?",
      "question_type": "multiple_choice",
      "options": {
        "A": "Reduction to absurdity",
        "B": "Reduction of abs",
        "C": "Reduce to silly",
        "D": "Reproduce to absurdity"
      },
      "correct": "A"
    }
  ]
}
```

True/false items use the same external quiz shape with a stricter option set:

```json
{
  "id": "q002",
  "question": "Is moral progress possible under relativism?",
  "question_type": "true_false",
  "options": {
    "A": "True",
    "B": "False"
  },
  "correct": "B"
}
```

Run the included chapter-one quiz benchmark:

```bash
uv run ethnos quiz-bench 1 \
  --quiz benchmarks/ethics_ch1_mc.json \
  --output data/runs/quiz-bench-ethics-ch1.json \
  --debug-retrieval
```

The MC-only `review-mc-quiz`, `validate-mc-quiz`, and `mc-bench` commands are
available when you need MC-specific reports and comparisons. Prefer
`review-quiz`, `validate-quiz`, and `quiz-bench` for mixed work so MC,
true/false, matching, and essay items follow one path. `mc-bench` defaults to
`--chars 300`; this was the fastest tested MC context size that preserved
accuracy on the fixed `caspian` benchmark. Mixed `quiz-bench` keeps
`--chars 900` for broader answer context.

Compare two MC-only benchmark runs:

```bash
uv run ethnos mc-compare \
  data/runs/mc-bench-baseline.json \
  data/runs/mc-bench-candidate.json \
  --output data/runs/mc-compare.json
```

Refresh normalized records from existing valid model outputs after changing
storage policy, without calling Ollama:

```bash
uv run ethnos refresh-records 1
```

The default database path is `data/ethnos.sqlite`. You can override it:

```bash
ETHNOS_DB_PATH=/path/to/ethnos.sqlite uv run ethnos db-info
```

## Ollama

The default model is `gemma-python` at `http://localhost:11434`.

```bash
uv run ethnos structure 1
```

Override defaults with:

```bash
ETHNOS_OLLAMA_MODEL=gemma-python
ETHNOS_OLLAMA_HOST=http://localhost:11434
ETHNOS_OLLAMA_TIMEOUT=300
ETHNOS_OLLAMA_STRUCTURE_NUM_PREDICT=2048
ETHNOS_OLLAMA_ANSWER_NUM_PREDICT=1536
ETHNOS_OLLAMA_NUM_CTX=8192
ETHNOS_OLLAMA_THINK=false
ETHNOS_OLLAMA_NUM_THREAD=
```

These values are also listed in [`.env.example`](.env.example).

By default ethnos sends `think=false` to Ollama because local Gemma models can
spend the whole output budget on hidden thinking tokens. `--debug-ollama`
reports `message_thinking_length` so this is visible during smoke checks.
Set `ETHNOS_OLLAMA_THINK=auto` to omit the request field, or use
`true`/`low`/`medium`/`high` for models where thinking improves quality.
`ETHNOS_OLLAMA_NUM_THREAD` is optional and should normally stay unset; use it
only for controlled local benchmarks.

For CPU-only tuning notes, host-specific Ollama service settings, SQLite
pragmas, and benchmark protocol, see
[docs/PERFORMANCE_TUNING.md](docs/PERFORMANCE_TUNING.md) and
[docs/hosts/](docs/hosts/).
For connection failures, empty responses, length cutoffs, and invalid JSON, see
[docs/OLLAMA_TROUBLESHOOTING.md](docs/OLLAMA_TROUBLESHOOTING.md).

The current local database baseline includes `ethics.pdf` and `history.pdf`.
Both documents have valid latest structured output for every chunk and complete
section labels. Non-core chunks are summary-only, so role-filtered retrieval and
quality reports stay focused on study material.
