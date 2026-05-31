# History Chapter 20 Agent Review Summary

This curated sample shows the review layer that Ethnos produces from a
CPU-local, source-grounded pass over a Canvas-style quiz.

## Run

- document: `history.pdf`
- document id: `2`
- quiz: `benchmarks/history_ch20_canvas.json`
- model: `gemma-python`
- profile: `review-local`
- web: disabled
- vision pages: off

## Result

- items reviewed: `20`
- verdicts: `{"key_supported": 20}`
- review priorities: `{"pass": 17, "inspect": 3}`
- evidence strength: `{"direct": 8, "strong": 7, "partial": 5}`
- quality findings: `{"duplicate_prompt": 2, "typo": 1}`

## Review Queue

| Priority | Item | Verdict | Evidence | Reason |
| --- | --- | --- | --- | --- |
| inspect | `ch20-q009` | `key_supported` | `direct` | Option text contains `Temperence`; intended spelling is `Temperance`. |
| inspect | `ch20-q015` | `key_supported` | `partial` | Prompt is duplicated by `ch20-q020`; the keyed answer is still supported. |
| inspect | `ch20-q020` | `key_supported` | `partial` | Prompt is duplicated by `ch20-q015`; the keyed answer is still supported. |

## Why This Matters

Ethnos does not only mark answers right or wrong. It separates the claims:

- whether the keyed answer is supported by local PDF evidence
- how directly the evidence supports the answer
- whether the item should pass, be inspected, or block release
- whether distractors are unsupported, plausible, or ambiguous
- whether the question itself has a quality issue

That makes the output useful as a reviewer-facing artifact instead of a black
box model score.
