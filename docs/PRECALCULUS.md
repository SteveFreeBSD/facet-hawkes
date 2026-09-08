# Pre-calculus setup

> **Historical procedure.** `precalc-local` is a local Ollama alias built on
> `caspian` from Qwen2.5-Math-7B; it does **not** exist on the current host
> `casbox`, and every figure below was measured there. `ethnos precalc-bench`
> still defaults to that alias, so pass `--model` explicitly here. Live Hawkes
> mathematics does not use this path at all -- Facet answers exactly first, and
> [Answer capabilities](ANSWER_CAPABILITIES.md) is the map of what that covers.

Ethnos keeps its `qwen3.5:9b` default for the existing courses and provides
`precalc-local` as the transitional math-specific Ollama model. On `caspian`,
the alias uses Qwen2.5-Math-7B-Instruct Q4_K_M at about 4.7 GB and runs fully
on the Vega GPU with a 4096-token context; the figures below were measured
there, on that host's models.

Create the alias from the checked-in model definition:

```bash
ollama pull hf.co/bartowski/Qwen2.5-Math-7B-Instruct-GGUF:Q4_K_M
ollama create precalc-local -f models/Modelfile.precalc
```

Run the fixed standalone math benchmark:

```bash
uv run ethnos precalc-bench \
  --model precalc-local \
  --output data/runs/precalc-qwen25-full.json
```

The initial 13-question September 1, 2026 host run scored 12/13 (92.3%) in
4m32s. It correctly
solved the complex-power expression `i^7 * 12/(6i^3) = 2`; its one miss was
the elementary logarithmic equation `log_3(x - 1) = 2`. Treat the model as a
tutor whose work should be checked, not as an authoritative answer key.

The staged screenshot architecture uses `qwen3.5:4b` as its primary reader,
an independent verifier, and exact SymPy operations before any
solver-model fallback. See
[Vision and Exact-Math Architecture](VISION_MATH_ARCHITECTURE.md) for the
settings, evidence, certainty contract, acceptance gate, and rollback.

## Add the course material

There is no graphical course menu. `ethnos documents` is the available-course
list. The checked-in workflow expects `data/incoming/precalc.pdf`; add it
without changing the model used by the existing courses:

```bash
uv run ethnos ingest-pdf data/incoming/precalc.pdf
uv run ethnos chunk DOCUMENT_ID
uv run ethnos label-sections DOCUMENT_ID --preset precalc --dry-run
uv run ethnos label-sections DOCUMENT_ID --preset precalc
uv run ethnos documents
uv run ethnos structure DOCUMENT_ID --model qwen3.5:9b --limit 1 --debug-ollama
uv run ethnos structure DOCUMENT_ID --model qwen3.5:9b --all-roles
```

The `precalc` preset is specific to the 1,094-page Stitz-Zeager corrected
edition whose SHA-256 begins `cbaa878abab9`. It labels all pages and chunks,
keeps the instructional text (including exercises and answers) in core
retrieval, labels front matter as admin, and treats the index as support
material. The `--all-roles` run matches the complete structure coverage of the
ethics and history documents without allowing non-core material into default
retrieval. Verify `section-status`, `structure-status`, and `quality-report`
after processing; the target is zero unlabeled pages/chunks, zero latest
failures, zero never-attempted chunks, and no core chunk missing both key terms
and questions.

Use `qwen3.5:9b` for structured extraction so the stored records are produced
by the same validated model as ethics and history. Use `precalc-local` for
math-specific question answering and quiz work.

For ordinary grounded questions, select the math model explicitly:

```bash
uv run ethnos ask DOCUMENT_ID "Explain the domain of this function" \
  --model precalc-local
```

To produce a shareable image of the answer plus the exact keyboard/homework and
LaTeX commands for the symbols used:

```bash
uv run ethnos ask DOCUMENT_ID "Solve this equation" \
  --model precalc-local \
  --answer-image data/runs/precalc-answer.png
```

The command writes both `precalc-answer.png` and the copyable
`precalc-answer.keys.txt`. It requires the local `pango-view` executable and
does not add another model request.

For a question supplied as a screenshot or photo, use the default specialized
OCR plus independent verifier and solve the resulting verified text:

```bash
uv run ethnos ask DOCUMENT_ID "Solve the attached problem" \
  --question-image path/to/problem.png \
  --answer-image data/runs/precalc-answer.png
```

For the shortest interactive path on `caspian`, keep the question visible and
run:

```bash
uv run ethnos ask DOCUMENT_ID "Solve the pictured problem" --capture-question
```

Spectacle opens a region selector. Drag around the question panel and release.
Ethnos automatically saves the capture, uses it as `--question-image`, and
writes the answer-only PNG and trace under `data/runs/captures/`, then opens the
PNG in the desktop image viewer. The PNG contains only the answer in visual
form, including stacked fractions and indexed-root symbols. It does not contain
directions, sources, or symbol-key guidance and does not control Firefox.

The default vision transcription uses two different models and includes
equations, choices, diagram details, interface metadata, and a list of anything
ambiguous. Both passes must agree before the solver runs. Quiz score counters and
Correct/Incorrect totals are excluded from answer choices. Exact polynomial
factor/expansion questions and supported numeric or positive-variable radical
simplifications use the exact SymPy/deterministic engine and zero solver-model
tokens. Indexed roots render as real radical symbols, and fractional results
render with a fraction slash instead of exposing LaTeX commands. Unsupported
image problems use the compact structured `qwen3.5:4b` fallback by default.
Screenshot answers render as concise answer-only
cards. If the vision passes genuinely disagree, crop or clarify the image or
type the exact expression; use `--accept-image-uncertainty` only after manually
checking the printed transcription. Identical screenshots reuse a compatible
two-pass transcription cache; pass `--no-question-image-cache` to force a fresh
read after changing model weights.

PyMuPDF text extraction may lose two-dimensional notation, graphs, or formulas
embedded as images. Type the expression when possible; use the rendered-page
Agent Review path when the visual layout is essential.

## Finish document 3 structural processing

The September 2 recovery command is checked in rather than embedded in a
transient systemd shell string:

```bash
systemd-run --user --unit=ethnos-precalc-finalize-v2 \
  --description="Finish and verify Ethnos Precalculus" \
  --working-directory=/home/steve/apps/ethnos \
  /home/steve/apps/ethnos/scripts/finalize_precalculus.sh
```

Monitor it with:

```bash
systemctl --user status ethnos-precalc-finalize-v2 --no-pager
journalctl --user -u ethnos-precalc-finalize-v2 -f
```

It is normal for the fan to rise while Ollama is actively processing.
Completion requires `609` valid chunks, zero failed or never-attempted chunks,
and zero unlabeled pages/chunks. The script uses the same `qwen3.5:9b`
extractor as the established ethics/history structure data; the new vision
models are for image questions, not a silent rebuild of existing records.
