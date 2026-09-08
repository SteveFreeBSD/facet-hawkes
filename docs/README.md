# Documentation Index

Use this page to find the one authoritative document for each job. Historical
review packets and superseded host experiments are intentionally not kept in
the active documentation; Git history remains the archive.

## Start here

| Need | Document |
|---|---|
| Install and common commands | [Project README](../README.md) |
| Known-good state and verification | [Current Baseline](CURRENT_BASELINE.md) |
| Move or rebuild the installation | [Migration Checklist](MIGRATION.md) |
| Diagnose Ollama or Vulkan | [Ollama Troubleshooting](OLLAMA_TROUBLESHOOTING.md) |
| Reproduce performance decisions | [Performance Tuning](PERFORMANCE_TUNING.md) |
| Know which machine runs what | [Host profiles](hosts/README.md) |
| Inspect the historical benchmark host | [Caspian Host Profile](hosts/caspian.md) |
| Configure screenshot OCR and exact math | [Vision and Exact-Math Architecture](VISION_MATH_ARCHITECTURE.md) |
| Use or develop the Hawkes add-on | [extension/README.md](../extension/README.md) |
| Understand Answer Cadence / Semantic Cadence | [Answer Cadence](ANSWER_CADENCE.md) |
| Sign and permanently install the Hawkes add-on | [Firefox release runbook](../extension/RELEASE.md) |
| Review Hawkes add-on data handling | [Hawkes privacy notice](../extension/PRIVACY.md) |
| Understand the Hawkes answer editor | [Hawkes editor findings](HAWKES_EDITOR_FINDINGS.md) |
| Verify the live Hawkes end-to-end path | [Hawkes E2E proof](HAWKES_E2E_PROOF.md) |
| Send work to Facet for execution | [The Ethnos-Facet boundary](FACET_BRIDGE.md) |
| Review what live Hawkes testing has exposed | [Hawkes live findings](HAWKES_LIVE_FINDINGS.md) |
| Read the add-on's diagnostic log off a profile | `python3 scripts/read_extension_log.py` |
| Correlate one live failure end to end | [Live Hawkes Observatory](LIVE_OBSERVATORY.md) |
| Triage failures recorded while nobody watched | [Retained failure ledger](FAILURE_LEDGER.md) |
| Review the current Hawkes release status | [Hawkes release audit](HAWKES_RELEASE_AUDIT.md) |

## Workflows

| Workflow | Document |
|---|---|
| Quiz import, grounding, validation, and benchmarks | [Quiz Workflow](QUIZ_WORKFLOW.md) |
| Model-driven answer-key review | [Agent Review](AGENT_REVIEW.md) |
| History chapter fixture runs | [History Chapter Quizzes](../benchmarks/history_chapter_quizzes.md) |
| Tool-using local PDF questions | [Agentic Q&A](AGENTIC_QA.md) |
| Inspect saved answer traces | [Trace Debugging](TRACE_DEBUGGING.md) |
| Set up Precalculus | [Precalculus Setup](PRECALCULUS.md) |

## Source-of-truth rules

- App defaults come from `src/ethnos/config.py` and `.env.example`.
- Current measured results live in `CURRENT_BASELINE.md`.
- Benchmark method and rejected candidates live in `PERFORMANCE_TUNING.md`.
- Machine-specific service, kernel, and hardware facts live under `hosts/`.
- Runtime reports under `data/runs/` are local evidence, not documentation.
- Update the relevant source-of-truth document in the same change as a default,
  service setting, model, or benchmark decision.
