You are converting course text into structured study knowledge.

Return only valid JSON matching the supplied schema. Do not include Markdown fences, commentary, or extra keys.

Use the source text only. Empty lists are better than weak, vague, or invented records.

Return a topic only when the chunk has one clear main subject with a useful summary.

Extract 2 to 5 key terms when the chunk defines or explains important concepts.
Prefer exact terms from the chunk.
Each key term must include a short definition grounded in the chunk.

Return 1 to 3 useful study questions when the chunk contains answerable material.
Each question must include a short answer based only on the chunk.
Do not include unanswered chapter questions as study questions unless the answer is present in the chunk.
It is acceptable to return an empty questions list.

Return examples only when the chunk itself provides examples. Do not invent examples.

Preserve source page references when they are present in the input metadata.

Required JSON keys: chunk_summary, topics, key_terms, examples, questions.

Source citation: {source_citation}

Chunk text:

{chunk_text}

JSON:
