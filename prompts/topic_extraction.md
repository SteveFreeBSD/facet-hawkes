You are converting course text into structured study knowledge.

Return only valid JSON matching the supplied schema. Do not include Markdown fences, commentary, or extra keys.

Use the source text only. Empty lists are better than weak, vague, or invented records.

All five top-level keys are required: chunk_summary, topics, key_terms, examples, questions.

Return 1 topic identifying the main subject of this chunk with a short summary.
If the chunk covers multiple distinct subjects, return one topic per subject (up to 3).
Always return at least one topic unless the chunk is purely administrative (e.g. table of contents, copyright).

Extract 2 to 5 key terms when the chunk defines or explains important concepts.
Prefer exact terms from the chunk.
Each key term must include a short definition grounded in the chunk.

Return 1 to 3 useful study questions when the chunk contains answerable material.
Each question must include a short answer based only on the chunk.
Do not include unanswered chapter questions as study questions unless the answer is present in the chunk.
It is acceptable to return an empty questions list.

Return examples when the chunk contains illustrative cases, thought experiments, scenarios, or worked-out applications.
Use the exact content from the chunk. Do not invent examples.
Return an empty examples list only when no such material is present.

Preserve source page references when they are present in the input metadata.

Source citation: {source_citation}

Chunk text:

{chunk_text}

JSON:
