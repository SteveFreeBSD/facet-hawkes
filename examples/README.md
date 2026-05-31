# Examples

These examples are small, curated review artifacts intended for GitHub readers.
Full runtime outputs, traces, PDFs, and SQLite databases remain under `data/`
and are intentionally ignored by git.

- [`history_ch20_agent_review_summary.md`](history_ch20_agent_review_summary.md):
  a compact Agent Review summary for the History chapter 20 Canvas quiz.
- [`history_ch20_agent_review_summary.json`](history_ch20_agent_review_summary.json):
  the same result as structured data.

The source command for the example is:

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
