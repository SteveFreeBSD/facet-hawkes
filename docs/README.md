# Documentation index

Six authorities. Each answers one question, and nothing else claims to answer
it. If two documents disagree, the authority wins and the other is a defect.

**New here? Read [Current state](CURRENT_STATE.md) first** — the whole system
in one page, with the names, the topology and the limits.

## The six authorities

| # | Question | Authority |
|---|---|---|
| 1 | What is the architecture, and where does everything run? | [The Ethnos-Facet boundary](FACET_BRIDGE.md) |
| 2 | What can be answered, what can be entered, and what is proven live? | [Answer capabilities](ANSWER_CAPABILITIES.md), rendered from `answer-capabilities.json` |
| 3 | Which model answers, on which device, and what do I reinstall? | [Runtime, models and deployment](RUNTIME_AND_DEPLOYMENT.md) |
| 4 | How does Answer Cadence work? | [Answer Cadence](ANSWER_CADENCE.md) |
| 5 | How do I look at a live failure without breaking anything? | [Hawkes development flow](HAWKES_DEVELOPMENT_FLOW.md) |
| 6 | What was true before, and what replaced it? | [Historical record](history/README.md) |

## Working on the live Hawkes system

| Need | Document |
|---|---|
| Orient from nothing | [Current state](CURRENT_STATE.md) |
| Correlate one live failure end to end, from one clock | [Live Hawkes Observatory](LIVE_OBSERVATORY.md) |
| Triage failures recorded while nobody was watching | [Retained failure ledger](FAILURE_LEDGER.md) |
| Understand what the Hawkes answer editor publishes | [Hawkes editor findings](HAWKES_EDITOR_FINDINGS.md) |
| Work on structured graph answers | [Structured parabola graph answers](HAWKES_GRAPH.md) |
| Use or develop the add-on | [`extension/README.md`](../extension/README.md) |
| Sign, install and roll back the add-on | [Firefox release runbook](../extension/RELEASE.md) |
| Review the add-on's data handling | [Hawkes privacy notice](../extension/PRIVACY.md) |
| Read the release position and its evidence | [Release audit ledger](HAWKES_RELEASE_AUDIT.md) |
| Read the add-on's diagnostic log off a profile | `python3 scripts/read_extension_log.py` |
| Confirm both repositories are consistent and buildable | [Verification checklist](VERIFICATION_CHECKLIST.md) |

## Working on the local study engine

A separate, older product surface in the same repository: PDF ingestion,
grounded Q&A, quiz import and audit, and model-driven review. It is not part of
a Hawkes solve. These documents describe procedure that was measured on
`caspian`; each says so at the top.

| Workflow | Document |
|---|---|
| Reproduce the study engine on another machine | [Migration checklist](MIGRATION.md) |
| Quiz import, grounding, validation and benchmarks | [Quiz workflow](QUIZ_WORKFLOW.md) |
| Model-driven answer-key review | [Agent review](AGENT_REVIEW.md) |
| Tool-using local PDF questions | [Agentic Q&A](AGENTIC_QA.md) |
| Inspect saved answer traces | [Trace debugging](TRACE_DEBUGGING.md) |
| Screenshot OCR and exact-math rollout | [Vision and exact-math architecture](VISION_MATH_ARCHITECTURE.md) |
| Set up pre-calculus | [Pre-calculus setup](PRECALCULUS.md) |
| Diagnose Ollama or Vulkan | [Ollama troubleshooting](OLLAMA_TROUBLESHOOTING.md) |
| History chapter fixture runs | [History chapter quizzes](../benchmarks/history_chapter_quizzes.md) |

## Source-of-truth rules

- Application defaults come from `src/ethnos/config.py` and `.env.example`.
- Facet's model assignment comes from `facet-runtime/src/facet_runtime/models.py`;
  `facet models` prints it.
- The required Facet runtime commit comes from `deploy/facet-runtime.pin`, and
  from nowhere else.
- The answer-shape and entry coverage map is `ANSWER_CAPABILITIES.md`, and
  `tests/test_answer_capabilities.py` fails when a new answer form has no row.
- Runtime reports under `data/runs/` are local evidence, not documentation.
- Update the relevant authority in the same change as a default, service
  setting, model, transport or protocol decision.
- A document that stops being instruction and becomes evidence moves to
  [`history/`](history/README.md) with a header saying what replaced it. It is
  not deleted.
