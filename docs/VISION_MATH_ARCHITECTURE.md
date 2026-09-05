# Vision and Exact-Math Architecture

Status: functionally validated candidate on `caspian`, 2026-09-02. The established
`gemma-python` baseline remains available for rollback until the screenshot
acceptance set passes.

This is the source of truth for image-question recognition, exact symbolic
calculation, model selection, rollout, and acceptance. It distinguishes
vendor-published model evidence from results actually observed in Ethnos.

## Objective and certainty contract

Ethnos must turn a screenshot or photo into a correct, compact answer image
without silently guessing a sign, exponent, fraction boundary, graph feature,
or answer choice. No generative model can guarantee 100% recognition, so the
system approaches that goal by requiring independent agreement and exact
verification. When a consequential ambiguity remains, the correct behavior is
to stop and expose it.

The pipeline is:

1. Crop or capture the problem panel at readable resolution.
2. Transcribe it with a specialized OCR model.
3. Independently re-read it with a different multimodal model.
4. Refuse to solve if the readings or explicit uncertainties disagree.
5. Retrieve textbook context using only the recognized problem text.
6. Prefer an exact deterministic operation for supported symbolic mathematics,
   including polynomial operations and supported numeric/indexed radicals.
7. Use a compact structured model answer only for unsupported problem types.
8. Render the final answer image and preserve the complete trace.

## Model roles

| Role | Selected candidate | Reason |
|---|---|---|
| Primary structured reader and fallback solver | `qwen3.5:4b` | Passed Ethos's strict JSON screenshot flow; about 3.4 GB |
| Independent structured verifier | the caspian-era alias | Passed the independent schema-based verification pass on that host |
| Formula-recognition candidate | `glm-ocr:q8_0` | Installed specialist; needs a dedicated plain-output adapter before routing |
| Exact symbolic engine | SymPy 1.14+ | Exact simplify/factor/expand operations and equivalence checks without model tokens |
| Transitional solver | `precalc-local` | Existing Qwen2.5-Math 7B rollback and second-opinion option |
| Ambiguous-case candidate | `qwen3.5:9b` | Optional later escalation; do not install or route by default yet |

Do not use the caspian-era text alias as the default screenshot reader. Local inspection
shows that alias has a Python-helper system prompt unrelated to image
transcription. It remains the validated extraction and ethics/history baseline
during the staged migration.

The model choices are supported by current primary sources:

- [GLM-OCR model card](https://huggingface.co/zai-org/GLM-OCR) and
  [official implementation](https://github.com/zai-org/GLM-OCR)
- [Qwen3.5-4B model card](https://huggingface.co/Qwen/Qwen3.5-4B) and
  [Ollama tags](https://ollama.com/library/qwen3.5/tags)
- [Gemma 4 model card](https://ai.google.dev/gemma/docs/core/model_card_4)
- [Qwen2.5-Math-7B model card](https://huggingface.co/Qwen/Qwen2.5-Math-7B-Instruct)
- [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs),
  [thinking](https://docs.ollama.com/capabilities/thinking), and
  [runtime FAQ](https://docs.ollama.com/faq)
- [SymPy simplification](https://docs.sympy.org/latest/tutorials/intro-tutorial/simplification.html)
  and [solver checking](https://docs.sympy.org/latest/modules/solvers/solvers.html)

Published scores are directional vendor results, not an Ethnos benchmark and
not a guarantee on the course UI. The user requested that model downloads and
configuration proceed without running a comparative benchmark; functional
smoke checks and normal regression tests are still required before use.

## Application settings

The candidate defaults are in `src/ethnos/config.py` and `.env.example`:

```text
ETHNOS_OLLAMA_VISION_MODEL=qwen3.5:4b
ETHNOS_OLLAMA_VISION_VERIFIER_MODEL=qwen3.5:9b
ETHNOS_OLLAMA_VISION_NUM_PREDICT=256
ETHNOS_OLLAMA_MATH_MODEL=qwen3.5:4b
ETHNOS_QUESTION_IMAGE_CACHE_DIR=data/cache/question_images
ETHNOS_OLLAMA_NUM_CTX=4096
ETHNOS_OLLAMA_THINK=false
ETHNOS_OLLAMA_KEEP_ALIVE=30m
```

Image transcription uses temperature zero, JSON schema output, 256 output
tokens per reader, and a 4096-token context. The exact-math path uses no model
tokens. The unsupported-problem structured solver is capped at 384 tokens.
Keep `OLLAMA_NUM_PARALLEL=1` on the single Vega iGPU; parallel model generation
would compete for the same device rather than reduce latency.

Keep flash attention, iGPU enablement, mlock, and unlimited memlock. Retain the
F16 KV cache while correctness is the priority. Restrict loaded models to two
when changing the persistent service so GLM-OCR and Qwen can coexist without
accumulating dormant runners.

The application sends a 30-minute keepalive even when no `.env` file is
present. The checked-in systemd drop-in applies the same fallback to non-Ethnos
Ollama callers once it is installed with administrator authority.

Successful two-reader transcriptions are cached by image content, instruction,
both model names, both prompts, context, and output budget. Reusing an identical
screenshot therefore skips both model calls. Pass `--no-question-image-cache`
after changing or retagging model weights, or clear the ignored cache directory,
to force fresh pixel inspection.

## Commands and rollback

Default candidate path:

```bash
uv run ethnos ask 3 "Solve the pictured problem" \
  --question-image path/to/problem.png \
  --answer-image data/runs/precalc-answer.png \
  --trace-dir data/runs
```

Safe interactive capture path on KDE:

```bash
uv run ethnos ask 3 "Solve the pictured problem" --capture-question
```

This starts Spectacle's user-controlled region selector and then runs the same
pipeline. It does not use WebDriver or a browser profile. The capture, automatic
answer-only PNG, and trace are stored together under `data/runs/captures/`; the
PNG opens automatically and no separate symbol-key file is generated. The PNG
contains only the answer in visual form, including stacked fractions and
indexed-root symbols, with no directions or source list.

Explicit candidate path:

```bash
uv run ethnos ask 3 "Solve the pictured problem" \
  --question-image path/to/problem.png \
  --vision-model qwen3.5:4b \
  --vision-verifier-model qwen3.5:9b \
  --vision-num-predict 256 \
  --model qwen3.5:4b \
  --answer-image data/runs/precalc-answer.png \
  --trace-dir data/runs
```

Rollback both passes to the previous reader without changing code:

```bash
uv run ethnos ask 3 "Solve the pictured problem" \
  --question-image path/to/problem.png \
  --vision-model qwen3.5:9b \
  --vision-verifier-model qwen3.5:9b \
  --model precalc-local
```

## Acceptance gate

Do not describe the candidate as 100% or remove rollback models until all of
these are true:

- Both image models load through Vulkan without an AMDGPU reset.
- The two supplied Question 10 and Question 11 screenshots transcribe exactly.
- The exact engine fully factors Question 10 and expands Question 11.
- A labeled set covers minus signs, exponents, radicals, fractions, plus/minus,
  inequalities, intervals, graphs, matrices, and noisy page chrome.
- Consequential disagreement fails closed unless the user explicitly accepts
  the printed uncertainty.
- Traces record both model names, both response summaries, the recognized text,
  selected source chunks, and deterministic/model solve status.
- The complete Python test suite, Ruff, formatting, compilation, documentation
  links, and diff checks pass.

The large labeled screenshot set is a future acceptance activity, not part of
the current setup pass. A functional smoke is not a benchmark.

## Precalculus document parity

Image answering and textbook ingestion have separate gates. At the start of
this rollout, document 3 has 609 chunks: 397 valid, 10 latest-failed, and 202
never attempted. Raw text and section labels are present, but structural
enrichment is not yet at ethics/history certainty.

The earlier transient finalizer waited for another process and then failed
because it referenced `/home/steve/.local/bin/uv`; the installed executable is
`/usr/bin/uv`. The checked-in `scripts/finalize_precalculus.sh` uses the correct
absolute paths, processes never-attempted chunks, retries only failures, rebuilds
normalized records, and prints the final section, structure, and quality
reports. Parity requires 609 valid, zero failed, zero never attempted, and zero
unlabeled pages or chunks.

## Rollout record

| Date | Change | State |
|---|---|---|
| 2026-09-02 | Installed `glm-ocr:q8_0` and `qwen3.5:4b` in Ollama | staged |
| 2026-09-02 | Added separate primary/verifier settings and 256-token OCR budget | staged |
| 2026-09-02 | Scoped the new math-model default to image questions; ethics/history retain Gemma | staged |
| 2026-09-02 | Added safe AST-to-SymPy exact factor/expand path | staged |
| 2026-09-02 | Removed solver-output instructions from screenshot retrieval query | staged |
| 2026-09-02 | Added content-addressed two-pass transcription cache | staged |
| 2026-09-02 | Replaced broken finalizer command with checked-in script | staged |
| 2026-09-02 | Question 11: both readers agreed; exact expansion produced the answer image | passed smoke |
| 2026-09-02 | Question 10: both readers agreed; SymPy fully factored and reverse-checked the trinomial | passed smoke |
| 2026-09-02 | GLM-OCR twice emitted truncated non-schema JSON at 256 and 512 tokens | removed from default |
| 2026-09-02 | Question 1: Qwen/Gemma agreed on `(-4)^2`; exact answer `16` | passed smoke |
| 2026-09-02 | Question 6: indexed cube root parsed exactly and rendered as `6∛3` | passed smoke |
| 2026-09-02 | Question 7: positive-variable radical fraction simplified exactly to `1/(5yz^7)` | passed smoke |

The smoke artifacts are
`data/runs/question-10-candidate-answer.png`,
`data/runs/question-11-candidate-answer.png`, and their corresponding trace
directories. These are functional evidence, not a comparative benchmark.
