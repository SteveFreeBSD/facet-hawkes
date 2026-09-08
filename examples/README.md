# Examples

These examples are small, curated review artifacts intended for GitHub readers.
Full runtime outputs, traces, PDFs, and SQLite databases remain under `data/`
and are intentionally ignored by git.

> **Historical evidence.** These were produced on `caspian` in July 2026,
> against the `gemma-python` alias that exists only on that machine. The
> commands below are kept as the exact provenance of the artifacts beside them;
> on this host, name a model it has -- see [Runtime, models and
> deployment](../docs/RUNTIME_AND_DEPLOYMENT.md).

- [`history_ch20_agent_review_summary.md`](history_ch20_agent_review_summary.md):
  a compact Agent Review summary for the History chapter 20 Canvas quiz.
- [`history_ch20_agent_review_summary.json`](history_ch20_agent_review_summary.json):
  the same result as structured data.
- [`history_ch27_e2e_findings.md`](history_ch27_e2e_findings.md): the complete
  Canvas import, source-grounding, benchmark, key-audit, Agent Review, and
  content-quality findings for History chapter 27.

The source command for the Chapter 20 example is:

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
