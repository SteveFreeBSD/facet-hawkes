Convert course text into structured study JSON.

Return only schema-valid JSON, with no Markdown, commentary, or extra keys.
Required keys: chunk_summary, topics, key_terms, examples, questions.
Use the source only; empty arrays are better than vague or invented records.

Rules:
- chunk_summary: 1 to 3 grounded sentences.
- topics: 1 main subject, up to 3 if distinct; each has name, summary, confidence.
- key_terms: 2 to 5 exact important concepts when defined or explained; each has term, definition.
- questions: 1 to 3 answerable study questions with short source-grounded answers; each has question, answer.
- examples: only explicit cases, thought experiments, scenarios, or applications; each has title, body.
- Do not copy unanswered chapter questions unless the answer is in the chunk.
- Use [] only when that record type is absent or the chunk is non-study material.
- Preserve source page references when present.

Source citation: {source_citation}

Chunk text:

{chunk_text}

JSON:
