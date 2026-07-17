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
| Inspect the primary host | [Caspian Host Profile](hosts/caspian.md) |

## Workflows

| Workflow | Document |
|---|---|
| Quiz import, grounding, validation, and benchmarks | [Quiz Workflow](QUIZ_WORKFLOW.md) |
| Model-driven answer-key review | [Agent Review](AGENT_REVIEW.md) |
| Tool-using local PDF questions | [Agentic Q&A](AGENTIC_QA.md) |
| Inspect saved answer traces | [Trace Debugging](TRACE_DEBUGGING.md) |

## Source-of-truth rules

- App defaults come from `src/ethnos/config.py` and `.env.example`.
- Current measured results live in `CURRENT_BASELINE.md`.
- Benchmark method and rejected candidates live in `PERFORMANCE_TUNING.md`.
- Machine-specific service, kernel, and hardware facts live under `hosts/`.
- Runtime reports under `data/runs/` are local evidence, not documentation.
- Update the relevant source-of-truth document in the same change as a default,
  service setting, model, or benchmark decision.
