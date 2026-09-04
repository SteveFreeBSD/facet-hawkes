# History Chapter 27 End-to-End Findings

Verified on `caspian` on 2026-07-19 against document `2`, `history.pdf`.

## Outcome

| Gate | Result |
|---|---:|
| Canvas import | 20 questions, 100 points, 20 keyed choices |
| Import and anchor validation | Passed |
| Deterministic grounding | 19 `pdf_grounded`, 1 `source_missing_in_local_pdf` |
| Unresolved / invalid anchors | 0 / 0 |
| Model benchmark | 19/19 correct (100%) |
| Instructor-key agreement | 19/19 (100%) |
| Local source coverage | 19/20 (95%) |
| Key conflict candidates | 0 |
| Invalid / no-context responses | 0 / 0 |
| Retried items / retries | 0 / 0 |
| Model benchmark elapsed | 3m 55.6s |
| Deterministic Agent verdicts | 17 supported / 2 human-review / 1 source-missing |
| Agent priorities | 6 pass / 13 inspect / 1 fix |
| Agent finalization path | 0 model / 20 deterministic fallback |
| Deterministic test suite | 246 passed |

The supplied label sequence is:

```text
B A D D B C B C D C D C C C C B A D B A
```

The normalized fixture preserves the Canvas question/option wording and key.
The raw fixture intentionally removes the pasted introductory request and
normalizes surrounding whitespace; it is not a byte-for-byte copy of the
attachment. Manifest metadata supplies provenance, retrieval hints, and review
notes without rewriting the quiz items.

## Source-Provenance Findings

- Items 1, 3-7, 10-16, and 20 are grounded in chapter 27 text.
- Item 2, Brown v. Board of Education, is grounded in chapter 26 chunks 203-204.
- Items 8, 9, 17, and 18 use chapter 28 or the chapter-boundary text in chunks
  220-222. Their answers are supported by the local book, but not strictly by
  chapter 27.
- Item 19, the Warren Court, has no adequate local PDF passage. It is tagged
  `external_source_item`, receives no retrieval queries or citations, is skipped
  from scoring, and remains visible as the sole source-gap finding.

The deterministic Agent layer is intentionally more conservative than the
model benchmark. Item 15 remains `needs_human_review` because the counterculture
answer is a conceptual paraphrase of the source. Item 16 remains
`needs_human_review` because the source says the Gulf of Tonkin Resolution
authorized deployment but does not explicitly state the keyed option's
“without a formal declaration of war” qualifier. These inspection findings do
not contradict the 19/19 model benchmark; they identify where lexical fallback
alone cannot establish the complete claim.

Source coverage therefore cannot honestly be reported as 100% with the current
PDF. Reaching 20/20 coverage requires adding an approved source that discusses
Warren Court criminal-procedure protections; pointing the item at unrelated
Brown v. Board text would be false grounding.

## Content-Quality Findings

- Item 5 calls Cesar Chavez the singular United Farm Workers leader. The keyed
  choice is correct among the options, but Dolores Huerta's cofounder role is
  omitted. Distractor `Reies Tijerin` also misspells Reies Tijerina; raw Canvas
  fidelity is preserved and the manifest records the note.
- Item 6 calls pesticide use an “environmental disaster.” `Pesticide use` is the
  intended answer, but “environmental problem” or “hazard” would be more precise.
- Item 9's supplied answer says Tet was a “military stalemate but a psychological
  victory.” The book more precisely describes a tactical communist defeat that
  exposed the credibility gap and eroded public trust. The key is the best
  available option, while the manifest explicitly records the wording caveat.
- Item 10 uses `Bloody Sunday` for the Selma-to-Montgomery march. More precisely,
  Bloody Sunday names the violent March 7 first attempt, not the entire later
  successful march.
- Items 9 and 18 substantially repeat the Tet Offensive learning objective.

## Monitor Improvements Made

- Shared Unicode-aware normalization now handles accents, Unicode dashes, soft
  hyphens, ordinary hyphens, and PDF line-wrap hyphenation consistently across
  anchor validation, option support, prompts, audit snippets, and evidence
  summaries.
- Declared anchors are exclusive context in grounding, benchmarking, and Agent
  Review. Every declared anchor is retained in manifest order, while unrelated
  retrieval and later inspection results are excluded from final citations.
- External-source and incomplete items skip retrieval entirely. Their source
  status, empty query history, empty evidence, zero confidence, and non-scoring
  status cannot be overwritten by incidental model output.
- Anchor validation now rejects non-integer chunk/page IDs and pages outside the
  declared chunks.
- Evidence matching uses token boundaries, case-sensitive acronym checks, and
  negation-to-answer binding to avoid substring and detached-qualifier false
  positives.
- Evidence excerpts center on keyed-answer or target language, so support late
  in a long chunk remains visible in the report. Only citations observed from
  successful tools are retained; model-authored citation fields are not trusted
  as provenance.
- Partial evidence and explicitly ambiguous distractors are escalated to
  `inspect`; direct evidence with confidence below 0.75 also stays inspectable.
  Same-chunk mentions alone are not called ambiguous. Instructor key notes are
  quality findings, missing source is always `fix`, and invalid anchors cannot
  pass or reach the answer model.
- Benchmark reports use `is_correct: null` for non-scoring items and expose
  scoring eligibility explicitly.
- Agent reports distinguish model-finalized items from deterministic fallbacks,
  deduplicate citations, and reset debug traces on a fresh run.
- Runtime Agent action validation rejects final-review payloads attached to
  ordinary tool calls and asks the model to correct malformed actions; repeated
  grounding calls are blocked after preflight. An explicit `--max-steps 0` mode
  provides a fast, reproducible deterministic audit without creating an Ollama
  client.

## Reproduction

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
  --model gemma-python \
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
  --model gemma-python \
  --profile review-local \
  --vision-pages off \
  --max-steps 0 \
  --item-timeout 0 \
  --debug-agent
```

Runtime JSON and Markdown artifacts remain under ignored `data/runs/`; this
checked-in document is the durable findings record.
