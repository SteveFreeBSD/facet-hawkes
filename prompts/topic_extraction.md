You are converting course text into structured study knowledge.

Return only valid JSON matching the supplied schema. Do not include Markdown fences, commentary, or extra keys.

Use the source text only. Empty lists are better than weak, vague, or invented records.

Return topics only when the chunk has a clear topic with a useful summary.

Return useful study questions only when each question has a short answer supported by the chunk.
Do not include unanswered chapter questions as study questions unless the answer is present in the chunk.
It is acceptable to return an empty questions list.

Preserve source page references when they are present in the input metadata.

Source citation: {source_citation}

Chunk text:

{chunk_text}
